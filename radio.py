import struct
import time
import zlib
from pathlib import Path

from pyrf24 import RF24, RF24_PA_LOW, RF24_1MBPS

from codec import encode_payload, save_payload
from logger import log

CE_PIN = 22
CSN_PIN = 0
MAX_RETRIES = 50

# The high bit marks a zlib stream. The other 31 bits count packets left.
PAYLOAD_SIZE = 32
HEADER = struct.Struct(">I")
CHUNK_SIZE = PAYLOAD_SIZE - HEADER.size
ZLIB_FLAG = 1 << 31
COUNT_MASK = ZLIB_FLAG - 1
MAX_PACKETS = COUNT_MASK + 1

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

def send_file(radio: RF24, file: Path, compression: bool = True) -> bool:
    data = file.read_bytes()
    original_size = len(data)
    data, compressed = encode_payload(data, compression)
    flag = ZLIB_FLAG if compressed else 0

    total = max(1, (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE)
    if total > MAX_PACKETS:
        log(f"File too big, it needs {total} packets (max {MAX_PACKETS})")
        return False

    radio.stop_listening()

    start = time.monotonic()
    for n in range(total):
        left = total - 1 - n
        chunk = data[n * CHUNK_SIZE:(n + 1) * CHUNK_SIZE]
        if not send_packet(radio, HEADER.pack(flag | left) + chunk):
            if n == 0:
                log("Receiver did not answer")
            else:
                log(f"Failed sending packet with {left} packets left")
            return False

    elapsed = time.monotonic() - start
    encoding = "zlib" if compressed else "raw"
    log(f"Sent {original_size} bytes as {len(data)} payload bytes "
        f"({encoding}) in {total} packets in {elapsed:.2f}s")
    return True

def receive_file(radio: RF24, file: Path) -> bool:
    radio.start_listening()
    log("Waiting for transmitter...")

    expected = None
    compressed = False
    data = bytearray()
    while expected is None or expected >= 0:
        if not radio.available():
            continue

        packet = radio.read(radio.get_dynamic_payload_size())
        if len(packet) < HEADER.size:
            continue

        header = HEADER.unpack_from(packet)[0]
        left = header & COUNT_MASK
        if expected is None:
            log(f"Receiving {left + 1} packets")
            expected = left
            compressed = bool(header & ZLIB_FLAG)

        # The ACK of the previous packet was lost and the TX sent it again
        if left == expected + 1:
            continue
        if left != expected:
            log(f"Unexpected packet with {left} packets left, expected {expected}")
            continue
        if bool(header & ZLIB_FLAG) != compressed:
            log("Packet encoding changed during transfer")
            radio.stop_listening()
            return False

        data += packet[HEADER.size:]
        expected -= 1

    radio.stop_listening()
    try:
        size = save_payload(file, data, compressed)
    except (OSError, ValueError, zlib.error) as error:
        log(f"Failed to save received file: {error}")
        return False
    log(f"Saved {size} bytes to {file}")
    return True
