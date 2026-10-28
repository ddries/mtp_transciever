import struct
import time
from pathlib import Path

from pyrf24 import RF24, RF24_PA_LOW, RF24_1MBPS

from logger import log

CE_PIN = 22
CSN_PIN = 0
MAX_RETRIES = 50

# Every packet is [packets left: 4 bytes, big endian][data: up to 28 bytes]
PAYLOAD_SIZE = 32
HEADER = struct.Struct(">I")
CHUNK_SIZE = PAYLOAD_SIZE - HEADER.size
MAX_PACKETS = 2 ** (8 * HEADER.size)

def setup_radio(address: str, channel: int) -> RF24 | None:
    radio = RF24(CE_PIN, CSN_PIN)
    if not radio.begin():
        return None

    radio.set_pa_level(RF24_PA_LOW)
    radio.data_rate = RF24_1MBPS
    radio.channel = channel
    radio.dynamic_payloads = True
    radio.set_retries(5, 15)

    addr = address.encode()
    radio.stop_listening(addr)
    radio.open_rx_pipe(1, addr)
    return radio

def send_packet(radio: RF24, packet: bytes) -> bool:
    for _ in range(MAX_RETRIES):
        if radio.write(packet):
            return True
        time.sleep(0.01)
    return False

def send_file(radio: RF24, file: Path) -> bool:
    data = file.read_bytes()

    # Number of packets, each CHUNK_SIZE bytes
    total = len(data) // CHUNK_SIZE
    if len(data) % CHUNK_SIZE != 0:
        total += 1

    # An empty file is still sent as one packet with no data
    if total == 0:
        total = 1
    if total > MAX_PACKETS:
        log(f"File too big, it needs {total} packets (max {MAX_PACKETS})")
        return False

    radio.stop_listening()

    start = time.monotonic()
    for n in range(total):
        left = total - 1 - n
        chunk = data[n * CHUNK_SIZE:(n + 1) * CHUNK_SIZE]
        if not send_packet(radio, HEADER.pack(left) + chunk):
            if n == 0:
                log("Receiver did not answer")
            else:
                log(f"Failed sending packet with {left} packets left")
            return False

    elapsed = time.monotonic() - start
    log(f"Sent {len(data)} bytes in {total} packets in {elapsed:.2f}s")
    return True

def receive_file(radio: RF24, file: Path) -> bool:
    radio.start_listening()
    log("Waiting for transmitter...")

    expected = None
    data = bytearray()
    while expected is None or expected >= 0:
        if not radio.available():
            continue

        packet = radio.read(radio.get_dynamic_payload_size())
        if len(packet) < HEADER.size:
            continue

        left = HEADER.unpack_from(packet)[0]
        if expected is None:
            log(f"Receiving {left + 1} packets")
            expected = left

        # The ACK of the previous packet was lost and the TX sent it again
        if left == expected + 1:
            continue
        if left != expected:
            log(f"Unexpected packet with {left} packets left, expected {expected}")
            continue

        data += packet[HEADER.size:]
        expected -= 1

    radio.stop_listening()
    file.write_bytes(data)
    log(f"Saved {len(data)} bytes to {file}")
    return True
