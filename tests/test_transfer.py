import random
import struct
import sys
import tempfile
import types
import unittest
import zlib
from collections import deque
from pathlib import Path
from unittest.mock import patch

# The RF24 extension requires board hardware. Only its import is stubbed.
driver = types.ModuleType("pyrf24")
driver.RF24 = object
driver.RF24_PA_LOW = driver.RF24_1MBPS = 0
with patch.dict(sys.modules, {"pyrf24": driver}):
    import radio


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
        if not self.packets:
            raise AssertionError("receiver requested a packet after the last one")
        return True

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

    def test_raw_fallback_at_packet_boundaries(self):
        for size in (0, 1, 27, 28, 29, 56, 57, 4096):
            with self.subTest(size=size):
                data = random.Random(42).randbytes(size)
                self.send(data)
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
