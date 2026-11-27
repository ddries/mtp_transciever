"""Pruebas deterministas; el transporte falso no modela propagación ni colisiones RF."""

import random
import io
import struct
import tempfile
import unittest
import zlib
from collections import deque
from pathlib import Path
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nmp import (ASK, BACKOFF, DATA, DONE, EXP, FRAME, GO, IDLE, RX, STATUS,
                 STOP, STOPPED, TX, FULL_MASK, MAX_FILE, Node, fragment,
                 pack_frame, reconstruct, unpack_frame)
from radio import ADDRESS, NRF24Radio


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeRadio:
    def __init__(self, clock, deliver=None):
        self.clock = clock
        self.deliver = deliver
        self.inbox = deque()
        self.sent = []
        self.listening = False
        self.end = None
        self.closed = False

    def listen(self):
        self.listening = True

    def stop(self):
        self.listening = False
        self.end = None

    def flush_rx(self):
        self.inbox.clear()

    def receive(self):
        if self.listening and self.inbox and self.inbox[0][1] <= self.clock():
            return self.inbox.popleft()
        return None

    def start_tx(self, payload):
        self.listening = False
        self.sent.append(payload)
        self.end = self.clock() + 0.00045
        if self.deliver is not None:
            self.deliver(self, payload, self.end)

    def tx_done(self):
        if self.end is not None and self.clock() >= self.end:
            end, self.end = self.end, None
            self.flush_rx()
            return end
        return None

    def close(self):
        self.closed = True


class Network:
    """Solo entrega tramas entre enlaces de prueba; Node no conoce estos índices."""

    def __init__(self, data, count=3):
        self.clock = Clock()
        self.links = {(i, i + 1) for i in range(count - 1)}
        self.drop = lambda sender, receiver, payload: False
        self.radios = [FakeRadio(self.clock, self.deliver) for _ in range(count)]
        self.nodes = [Node(radio, data if i == 0 else None, clock=self.clock,
                           rng=random.Random(100 + i)) for i, radio in enumerate(self.radios)]
        for node in self.nodes:
            node.handle(GO)

    def deliver(self, radio, payload, end):
        sender = self.radios.index(radio)
        for receiver, other in enumerate(self.radios):
            link = tuple(sorted((sender, receiver)))
            if link in self.links and other.listening and not self.drop(sender, receiver, payload):
                other.inbox.append((payload, end))

    def run(self, seconds):
        for _ in range(round(seconds * 1000)):
            self.clock.now += 0.001
            for node in self.nodes:
                node.poll()

    def until(self, condition, limit=5):
        for _ in range(limit * 1000):
            if condition():
                return
            self.run(0.001)
        raise AssertionError([(n.state, n.have, n.send, n.ask, n.complete) for n in self.nodes])

    def quiet(self):
        return all(n.complete and n.state == IDLE and not n.pending for n in self.nodes)


def sample(size):
    return bytes(i % 256 for i in range(size))  # Incluye NUL, CR, LF y bytes no UTF-8.


class NMPTests(unittest.TestCase):
    def make_node(self, source=None, output=None):
        clock = Clock()
        radio = FakeRadio(clock)
        node = Node(radio, source, output, clock, random.Random(7))
        node.handle(GO)
        return node, radio, clock

    def snapshot(self, node):
        return (node.state, node.have, node.send, node.ask, node.complete, node.n,
                node.chunks[:], node.backoff_at, node.ask_at)

    def receive(self, node, data, order=None):
        chunks = fragment(data)
        have = (1 << len(chunks)) - 1
        for seq in range(len(chunks)) if order is None else order:
            node.handle(RX, pack_frame(DATA, have, seq, chunks[seq]))

    def test_binary_format_and_exact_files(self):
        self.assertEqual(pack_frame(STATUS, 0x12345678), b"\x20\x78\x56\x34\x12" + bytes(27))
        self.assertEqual(pack_frame(DATA, FULL_MASK, 31, b"a" * 27), b"\x5f" + b"\xff" * 4 + b"a" * 27)
        for size, n in ((0, 1), (500, 19), (858, 32)):
            with self.subTest(size=size):
                data = sample(size)
                chunks = fragment(data)
                self.assertEqual(len(chunks), n)
                self.assertEqual(chunks[0][:6], struct.pack("<HI", size, zlib.crc32(data)))
                self.assertEqual(b"".join(chunks)[6 + size:], bytes(n * 27 - 6 - size))
                self.assertEqual(reconstruct(chunks), data)
                node, _, _ = self.make_node()
                self.receive(node, data)
                self.assertTrue(node.complete)
                self.assertIsNone(node.ask_at)
                self.assertEqual(reconstruct(node.chunks), data)

    def test_truncation(self):
        with self.assertLogs(level="WARNING") as messages:
            chunks = fragment(sample(1000))
        self.assertIn("858", messages.output[0])
        self.assertEqual(reconstruct(chunks), sample(1000)[:MAX_FILE])

    def test_out_of_order_and_late_n_discards_out_of_range_storage(self):
        data = sample(500)
        node, _, _ = self.make_node()
        node.handle(RX, pack_frame(DATA, FULL_MASK, 31, b"x" * 27))
        self.receive(node, data, range(18, 0, -1))
        self.assertIsNone(node.n)
        self.assertFalse(node.complete)
        self.assertTrue(node.have & (1 << 31))
        self.receive(node, data, [0])
        self.assertEqual(node.n, 19)
        self.assertEqual(node.have, (1 << 19) - 1)
        self.assertEqual(node.send >> 19, 0)
        self.assertTrue(all(c is None for c in node.chunks[19:]))
        self.assertEqual(reconstruct(node.chunks), data)
        self.assertTrue(node.complete)

    def test_duplicate_suppression_precedes_repair(self):
        node, _, _ = self.make_node()
        chunk = fragment(sample(40))[0]
        node.handle(RX, pack_frame(DATA, 1, 0, chunk))
        self.assertEqual(node.send, 1)
        request_deadline = node.ask_at
        node.handle(RX, pack_frame(DATA, 1, 0, chunk), at=0.05)
        self.assertEqual(node.send, 0)
        self.assertEqual(node.state, IDLE)
        self.assertIsNone(node.backoff_at)
        self.assertEqual(node.ask_at, request_deadline)
        node.handle(RX, pack_frame(DATA, 0, 0, chunk), at=0.06)
        self.assertEqual(node.send, 1)  # Reparación después de supresión.
        self.assertEqual(node.state, BACKOFF)

    def test_malformed_frames_leave_everything_unchanged(self):
        node, _, _ = self.make_node()
        self.receive(node, sample(40), [0])
        invalid = [None, "not bytes", b"", bytes(31), bytes(33)]
        invalid += [FRAME.pack(tag, FULL_MASK, bytes(27)) for tag in (0, 0x60, 0x80, 0xA0, 0xC0, 0xE0)]
        invalid += [pack_frame(DATA, FULL_MASK, 2, bytes(27)),
                    pack_frame(DATA, 1, 0, struct.pack("<HI", 859, 0) + bytes(21))]
        before = self.snapshot(node)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertFalse(node.handle(RX, payload, at=0.1))
                self.assertEqual(self.snapshot(node), before)
        self.assertIsNone(unpack_frame(invalid[-1]))

    def test_validation_uses_pdf_rules_without_extra_rejections(self):
        # 5.2: STATUS no se rechaza por SEQ/DATA; HAVE alto se ignora con N conocido.
        raw = FRAME.pack(STATUS | 31, FULL_MASK, b"x" * 27)
        self.assertEqual(unpack_frame(raw, 2)[2], 3)
        node, _, _ = self.make_node(sample(40))
        self.assertTrue(node.handle(RX, raw))
        self.assertEqual(node.send, 3)
        unknown, _, _ = self.make_node()
        self.assertTrue(unknown.handle(RX, pack_frame(DATA, 0, 31, bytes(27))))
        self.assertEqual(unknown.have, 1 << 31)

    def test_timer_transitions_and_tx_uses_current_have(self):
        node, radio, _ = self.make_node()
        with patch.object(node.rng, "randint", return_value=4), patch.object(node.rng, "uniform", return_value=0.3):
            node.handle(ASK, at=1.0)
            self.assertAlmostEqual(node.backoff_at, 1.008)  # M1
            self.receive(node, sample(40), [1])
            node.handle(RX, pack_frame(STATUS, 0), at=1.003)
            self.assertAlmostEqual(node.backoff_at, 1.011)  # M2 sustituye el plazo.
            node.handle(ASK, at=1.004)
            self.assertAlmostEqual(node.backoff_at, 1.011)
            self.assertAlmostEqual(node.ask_at, 1.304)
            self.receive(node, sample(40), [0])  # HAVE actual: 0b11, no 0b10.
            node.handle(EXP, at=1.011)
            kind, seq, have, _ = unpack_frame(radio.sent[-1])
            self.assertEqual((kind, seq, have), (DATA, 0, 3))
            self.assertEqual(node.state, TX)
            self.assertFalse(node.ask)
            self.assertIsNone(node.backoff_at)
            before = self.snapshot(node)
            self.assertFalse(node.handle(RX, pack_frame(STATUS, 0)))
            self.assertEqual(self.snapshot(node), before)
            node.handle(DONE, at=1.020)
            self.assertAlmostEqual(node.backoff_at, 1.028)  # M3
            self.assertTrue(radio.listening)

    def test_ask_during_tx_and_status_clears_ask(self):
        node, radio, _ = self.make_node()
        self.assertGreaterEqual(node.ask_at, 0.150)
        self.assertLessEqual(node.ask_at, 0.450)
        node.handle(ASK, at=1)
        node.handle(EXP, at=1.04)
        self.assertEqual(radio.sent[-1], pack_frame(STATUS, 0))
        self.assertFalse(node.ask)
        node.handle(ASK, at=1.5)
        self.assertTrue(node.ask)
        self.assertEqual(node.state, TX)
        self.assertIsNone(node.backoff_at)
        node.handle(DONE, at=1.501)
        self.assertEqual(node.state, BACKOFF)
        self.assertGreaterEqual(node.backoff_at, 1.503)
        self.assertLessEqual(node.backoff_at, 1.533)

    def test_poll_requires_controller_done(self):
        node, radio, clock = self.make_node(b"")
        clock.now = node.backoff_at
        node.poll()
        self.assertEqual(node.state, TX)
        node.poll()  # El controlador todavía está ocupado.
        self.assertEqual(node.state, TX)
        self.assertFalse(radio.listening)
        clock.now = radio.end
        node.poll()
        self.assertEqual(node.state, IDLE)
        self.assertTrue(radio.listening)

    def test_invalid_input_does_not_block_an_expired_timer(self):
        node, radio, clock = self.make_node()
        clock.now = node.ask_at
        radio.inbox.append((bytes(32), clock()))  # TYPE inválido; no es un evento RX.
        node.poll()
        self.assertEqual(node.state, BACKOFF)
        self.assertTrue(node.ask)
        self.assertGreater(node.ask_at, clock())

    def test_crc_failure_wipes_and_requests_immediately_then_recovers(self):
        data = sample(500)
        chunks = fragment(data)
        damaged = bytearray(chunks[5])
        damaged[7] ^= 0x80
        chunks[5] = bytes(damaged)
        node, radio, _ = self.make_node()
        with self.assertLogs(level="WARNING"):
            for seq, chunk in enumerate(chunks):
                node.handle(RX, pack_frame(DATA, (1 << 19) - 1, seq, chunk))
        self.assertEqual(node.have, 0)
        self.assertEqual(node.send, 0)
        self.assertIsNone(node.n)
        self.assertFalse(node.complete)
        self.assertTrue(all(c is None for c in node.chunks))
        self.assertTrue(node.ask)
        self.assertEqual(node.state, BACKOFF)
        self.assertLess(node.backoff_at, node.ask_at)
        node.handle(EXP, at=node.backoff_at)
        self.assertEqual(radio.sent[-1], pack_frame(STATUS, 0))
        node.handle(DONE)
        self.receive(node, data)
        self.assertTrue(node.complete)
        self.assertEqual(reconstruct(node.chunks), data)

    def test_stop_output_and_go_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "copy.bin"
            node, radio, _ = self.make_node(output=output)
            self.receive(node, sample(500))
            self.assertFalse(output.exists())
            self.assertNotEqual(node.state, STOPPED)
            node.handle(STOP)
            self.assertEqual(output.read_bytes(), sample(500))
            self.assertEqual(node.state, STOPPED)
            self.assertIsNone(node.ask_at)
            self.assertIsNone(node.backoff_at)
            self.assertFalse(radio.listening)
            radio.inbox.append((pack_frame(STATUS, 0), 0))
            node.handle(GO)
            self.assertFalse(radio.inbox)
            self.assertEqual(node.have, 0)
            self.assertFalse(node.complete)
            with self.assertLogs(level="WARNING"):
                node.handle(STOP)
            self.assertEqual(output.read_bytes(), sample(500))

    def test_three_node_chain_and_quiescence(self):
        for size in (0, 500, 858):
            with self.subTest(size=size):
                network = Network(sample(size))
                self.assertNotIn((0, 2), network.links)
                network.until(network.quiet)
                for node in network.nodes:
                    self.assertEqual(reconstruct(node.chunks), sample(size))
                    self.assertIsNone(node.ask_at)
                    self.assertIsNone(node.backoff_at)
                counts = [len(r.sent) for r in network.radios]
                network.run(1)
                self.assertEqual([len(r.sent) for r in network.radios], counts)

    def test_lost_tail_is_repaired_by_requests(self):
        network = Network(sample(500), count=2)
        network.drop = lambda sender, receiver, payload: sender == 0 and payload[0] == (DATA | 18)
        network.run(1)
        self.assertFalse(network.nodes[1].complete)
        self.assertFalse(network.nodes[1].have & (1 << 18))
        self.assertTrue(any(f[0] == STATUS for f in network.radios[1].sent))
        network.drop = lambda *args: False
        network.until(network.quiet)
        self.assertEqual(reconstruct(network.nodes[1].chunks), sample(500))

    def test_link_cut_restoration_and_complete_nodes_helping(self):
        network = Network(sample(858))
        network.until(lambda: network.nodes[2].have.bit_count() >= 3)
        network.links.remove((1, 2))
        network.until(lambda: network.nodes[1].complete)
        network.run(1)
        self.assertFalse(network.nodes[2].complete)
        self.assertEqual(network.nodes[1].state, IDLE)
        self.assertIsNone(network.nodes[1].ask_at)
        sent_before = len(network.radios[1].sent)
        network.links.add((1, 2))
        network.until(network.quiet)
        self.assertTrue(any(f[0] & 0xE0 == DATA for f in network.radios[1].sent[sent_before:]))
        self.assertEqual(reconstruct(network.nodes[2].chunks), sample(858))

    def test_corrupted_chunk_in_chain_is_recovered_from_origin(self):
        network = Network(sample(500))
        corrupted = False

        def corrupt_once(radio, payload, end):
            nonlocal corrupted
            if not corrupted and payload[0] == (DATA | 5):
                damaged = bytearray(payload)
                damaged[12] ^= 0x80
                payload = bytes(damaged)
                corrupted = True
            network.deliver(radio, payload, end)

        network.radios[0].deliver = corrupt_once
        with self.assertLogs(level="WARNING") as messages:
            network.until(network.quiet)
        self.assertTrue(corrupted)
        self.assertTrue(any("CRC-32" in message for message in messages.output))
        for node in network.nodes:
            self.assertEqual(reconstruct(node.chunks), sample(500))

    def test_cli_source_stop_writes_and_closes_transport(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.bin", Path(directory) / "out.bin"
            source.write_bytes(sample(500))
            radio = FakeRadio(Clock())
            with patch("main.UDPRadio", return_value=radio), patch("main.time.sleep", side_effect=KeyboardInterrupt):
                result = main.main(["--radio", "udp", "--input", str(source), "--output", str(output), "--go"])
            self.assertEqual(result, 0)
            self.assertEqual(output.read_bytes(), sample(500))
            self.assertTrue(radio.closed)


class RadioTests(unittest.TestCase):
    """Contrato con la API publicada de pyrf24; no sustituye pruebas con el módulo."""

    def driver(self):
        device = Mock(spec_set=[
            "begin", "stop_listening", "set_auto_ack", "set_retries", "toggle_all_pipes",
            "open_rx_pipe", "ce_pin", "flush_tx", "flush_rx", "clear_status_flags",
            "start_write", "update", "available", "read", "channel", "address_width",
            "dynamic_payloads", "ack_payloads", "payload_size", "data_rate", "crc_length",
            "pa_level", "power", "listen",
        ])
        device.begin.return_value = True
        device.start_write.return_value = True
        device.update.return_value = 0
        device.available.return_value = False
        module = SimpleNamespace(
            RF24=Mock(return_value=device), RF24_DRIVER="SPIDEV", RF24_1MBPS=0,
            RF24_CRC_16=2, RF24_PA_MIN=0, RF24_PA_LOW=1, RF24_PA_HIGH=2,
            RF24_PA_MAX=3, RF24_TX_DS=0x20, RF24_TX_DF=0x10,
        )
        return device, module

    def open_radio(self, module):
        with patch("radio.sys.platform", "linux"), patch.dict("sys.modules", {"pyrf24": module}):
            return NRF24Radio(17, 10, "low")  # Valores de prueba, no cableado del proyecto.

    def test_nrf24_configuration_and_stopped_until_go(self):
        device, module = self.driver()
        radio = self.open_radio(module)
        module.RF24.assert_called_once_with(17, 10)
        self.assertEqual((device.channel, device.address_width, device.payload_size), (79, 5, 32))
        self.assertEqual((device.data_rate, device.crc_length, device.pa_level), (0, 2, 1))
        self.assertFalse(device.dynamic_payloads)
        self.assertFalse(device.ack_payloads)
        device.set_auto_ack.assert_called_once_with(False)
        device.set_retries.assert_called_once_with(0, 0)
        device.stop_listening.assert_called_with(ADDRESS)
        device.toggle_all_pipes.assert_called_once_with(False)
        device.open_rx_pipe.assert_called_once_with(1, ADDRESS)
        self.assertFalse(device.power)
        self.assertFalse(radio.listening)
        device.start_write.assert_not_called()

    def test_nrf24_nonblocking_tx_requires_fresh_tx_ds(self):
        device, module = self.driver()
        radio = self.open_radio(module)
        node = Node(radio, b"", clock=Clock(), rng=random.Random(1))
        node.handle(GO)
        node.handle(EXP)
        device.start_write.assert_called_once_with(pack_frame(DATA, 1, 0, fragment(b"")[0]), False)
        self.assertFalse(radio.listening)
        cleared = device.clear_status_flags.call_count
        self.assertIsNone(radio.tx_done())  # Cargar el FIFO no equivale a DONE.
        self.assertEqual(device.clear_status_flags.call_count, cleared)
        device.update.return_value = module.RF24_TX_DS
        with patch("radio.time.monotonic", return_value=12.5):
            node.poll()
        self.assertEqual(node.state, IDLE)
        self.assertTrue(radio.listening)
        self.assertTrue(device.listen)
        node.handle(STOP)
        self.assertFalse(device.power)
        self.assertIsNone(radio.tx_done())

    def test_nrf24_receive_and_close(self):
        device, module = self.driver()
        radio = self.open_radio(module)
        device.available.return_value = True
        device.read.return_value = bytearray(pack_frame(STATUS, 0))
        self.assertIsNone(radio.receive())
        radio.listen()
        with patch("radio.time.monotonic", return_value=3.25):
            self.assertEqual(radio.receive(), (pack_frame(STATUS, 0), 3.25))
        device.read.assert_called_once_with(32)
        radio.close()
        self.assertFalse(device.power)
        self.assertIsNone(radio.device)
        self.assertIsNone(radio.receive())

    def test_nrf24_reports_missing_device_and_unexpected_retry(self):
        device, module = self.driver()
        device.begin.return_value = False
        with self.assertRaisesRegex(RuntimeError, "No se detecta"):
            self.open_radio(module)
        device.start_write.assert_not_called()
        device.begin.return_value = True
        radio = self.open_radio(module)
        radio.listen()
        radio.start_tx(pack_frame(STATUS, 0))
        device.update.return_value = module.RF24_TX_DF
        with self.assertRaisesRegex(RuntimeError, "MAX_RT"):
            radio.tx_done()
        self.assertFalse(device.power)

    def test_cli_does_not_assume_hardware_pins_or_power(self):
        import main

        with patch("main.NRF24Radio") as constructor, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_status:
                main.main([])
        self.assertEqual(exit_status.exception.code, 2)
        constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
