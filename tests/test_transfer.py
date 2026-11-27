import random
import struct
import sys
import tempfile
import time
import types
import unittest
import zlib
from collections import deque
from pathlib import Path
from unittest.mock import patch

# The RF24 extension requires board hardware. Only its import is stubbed.
driver = types.ModuleType("pyrf24")
driver.RF24 = object
for name in ("RF24_PA_MIN", "RF24_PA_LOW", "RF24_PA_HIGH", "RF24_PA_MAX",
             "RF24_250KBPS", "RF24_1MBPS", "RF24_2MBPS"):
    setattr(driver, name, 0)
with patch.dict(sys.modules, {"pyrf24": driver}):
    from mtp import p2p as radio


class PacketRadio:
    def __init__(self):
        self.packets = deque()

    def write(self, packet):
        self.packets.append(packet)
        return True

    def start_listening(self):
        pass

    def stop_listening(self):
        pass

    def available(self):
        return bool(self.packets)

    def get_dynamic_payload_size(self):
        return len(self.packets[0])

    def read(self, size):
        packet = self.packets.popleft()
        assert len(packet) == size
        return packet


class TransferTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "input"
        self.output = Path(directory.name) / "output.txt"
        self.link = PacketRadio()
        # Short timeouts so the failure tests finish quickly
        for name, value in (("LINGER_S", 0.01), ("RECEIVE_TIMEOUT_S", 0.2), ("SEND_TIMEOUT_S", 0.2)):
            patcher = patch.object(radio, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self, data, **options):
        self.source.write_bytes(data)
        self.assertTrue(radio.send_file(self.link, self.source, **options))

    def receive(self, data):
        self.assertTrue(radio.receive_file(self.link, self.output))
        self.assertEqual(self.output.read_bytes(), data)

    def test_compressed_binary_with_duplicate_packet(self):
        data = bytes(range(256)) * 128
        self.send(data)
        packets = self.link.packets
        self.assertGreater(len(packets), 1)
        self.assertLess(len(packets), (len(data) + 27) // 28)
        for index, packet in enumerate(packets):
            self.assertLessEqual(len(packet), 32)
            header, = struct.unpack(">I", packet[:4])
            self.assertEqual(header, (1 << 31) | (len(packets) - index - 1))
        # Simulate a lost ACK and the resulting retransmission.
        packets.appendleft(packets[0])
        self.receive(data)

    def test_incompressible_data_goes_as_checked_zlib(self):
        # Never raw with compression on: stored blocks (+11 bytes) keep the Adler-32 check
        for size in (0, 1, 27, 28, 29, 56, 57, 4096):
            with self.subTest(size=size):
                data = random.Random(42).randbytes(size)
                self.send(data)
                payload = b"".join(p[4:] for p in self.link.packets)
                self.assertEqual(payload, zlib.compress(data, 0))
                for p in self.link.packets:
                    self.assertTrue(struct.unpack(">I", p[:4])[0] & (1 << 31))
                self.receive(data)

    def test_flipped_bit_in_incompressible_file_rejected(self):
        data = random.Random(7).randbytes(1000)
        self.send(data)
        packets = list(self.link.packets)
        damaged = bytearray(packets[10])
        damaged[8] ^= 0x10                       # a corrupt frame that passed the radio CRC
        packets[10] = bytes(damaged)
        self.link.packets = deque(packets)
        self.assertFalse(radio.receive_file(self.link, self.output))
        self.assertFalse(self.output.exists())

    def test_join_mid_transfer_rejected(self):
        # The receiver started late (or restarted) and missed the first packets
        data = random.Random(3).randbytes(5000)
        self.send(data)
        for _ in range(10):
            self.link.packets.popleft()
        self.assertFalse(radio.receive_file(self.link, self.output))
        self.assertFalse(self.output.exists())

    def test_receiver_gives_up_instead_of_hanging(self):
        # Bit flipped in the packets-left field: the radio ACKed it, the transmitter moved on,
        # and every later packet looks unexpected. Before the fix this looped forever.
        data = bytes(range(256)) * 64
        self.send(data)
        packets = list(self.link.packets)
        damaged = bytearray(packets[5])
        damaged[3] ^= 0x04
        packets[5] = bytes(damaged)
        self.link.packets = deque(packets)
        start = time.monotonic()
        self.assertFalse(radio.receive_file(self.link, self.output))
        self.assertLess(time.monotonic() - start, 2)
        self.assertFalse(self.output.exists())

    def test_transmitter_gives_up_at_deadline(self):
        class Silent(PacketRadio):
            def write(self, packet):
                return False
        self.source.write_bytes(b"hello")
        start = time.monotonic()
        self.assertFalse(radio.send_file(Silent(), self.source))
        self.assertLess(time.monotonic() - start, 2)

    def test_transmitter_rides_out_an_outage(self):
        # 80 failed writes in a row (someone walks between the boxes): the old 50-try limit gave up
        class Outage(PacketRadio):
            def __init__(self):
                super().__init__()
                self.failures = 80
            def write(self, packet):
                if self.failures:
                    self.failures -= 1
                    return False
                return super().write(packet)
        link = Outage()
        self.source.write_bytes(b"x" * 100)
        with patch.object(radio, "SEND_TIMEOUT_S", 10.0), patch.object(radio.time, "sleep", lambda s: None):
            self.assertTrue(radio.send_file(link, self.source))
        self.link = link
        self.receive(b"x" * 100)

    def test_retransmitted_last_packet_is_drained(self):
        # Lost ACK on the last packet: the copy must be ACKed (receiver still listening), not saved
        data = b"last packet ACK test " * 10
        self.send(data)
        self.link.packets.append(self.link.packets[-1])
        self.receive(data)
        self.assertEqual(len(self.link.packets), 0)

    def test_raw_legacy_mode_at_packet_boundaries(self):
        for size in (0, 1, 27, 28, 29, 56, 57, 4096):
            with self.subTest(size=size):
                data = random.Random(42).randbytes(size)
                self.send(data, compression=False)
                chunks = [data[i:i + 28] for i in range(0, size, 28)] or [b""]
                legacy = [struct.pack(">I", len(chunks) - i - 1) + chunk
                          for i, chunk in enumerate(chunks)]
                self.assertEqual(list(self.link.packets), legacy)
                self.receive(data)

    def test_compressed_stream_across_decoder_chunks(self):
        block = random.Random(17).randbytes(8192)
        data = block * 12
        self.send(data)
        self.assertGreater(sum(len(p) - 4 for p in self.link.packets), 4096)
        self.assertEqual(self.link.packets[-1][:4], struct.pack(">I", 1 << 31))
        self.receive(data)

    def test_legacy_mode_preserves_zlib_looking_bytes(self):
        data = zlib.compress(b"already compressed") + b"\x00" * 1000
        self.send(data, compression=False)
        self.assertEqual(b"".join(p[4:] for p in self.link.packets), data)
        self.assertEqual(self.link.packets[-1][:4], bytes(4))
        self.receive(data)

    def test_invalid_stream_leaves_existing_output_intact(self):
        data = zlib.compress(b"a" * 1000)
        self.output.write_bytes(b"previous file")
        damaged = data[:-1] + bytes([data[-1] ^ 1])
        for payload in (data[:-1], damaged, data + b"extra", b""):
            with self.subTest(payload=payload):
                self.link.packets.append(struct.pack(">I", 1 << 31) + payload)
                self.assertFalse(radio.receive_file(self.link, self.output))
                self.assertEqual(self.output.read_bytes(), b"previous file")
                self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    def test_inconsistent_encoding_rejected(self):
        self.link.packets.extend([struct.pack(">I", (1 << 31) | 1) + bytes(28),
                                  struct.pack(">I", 0) + b"tail"])
        self.assertFalse(radio.receive_file(self.link, self.output))
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
