import os
import struct
import time
import zlib
from pathlib import Path

from pyrf24 import (RF24, RF24_PA_MIN, RF24_PA_LOW, RF24_PA_HIGH, RF24_PA_MAX,
                    RF24_250KBPS, RF24_1MBPS, RF24_2MBPS)

from codec import encode_payload, save_payload
from logger import log

CE_PIN = 22      # Pi header pin 15
CSN_PIN = 0      # /dev/spidev0.0, CSN = GPIO 8 (header pin 24)
MAX_RETRIES = 50

# Ebyte E01-ML01SP4: a PA after the nRF24 (~+20..25 dB, measured in T0). On one fixed channel
# the limit is 10 mW e.i.r.p. (CNAF UN-85 b), so over the air only "min" (-18 dBm chip) is legal.
# "low"/"high"/"max" are for a pigtail into a >= 30 dB attenuator only.
PA_LEVELS = {"min": RF24_PA_MIN, "low": RF24_PA_LOW, "high": RF24_PA_HIGH, "max": RF24_PA_MAX}
DATA_RATES = {"250k": RF24_250KBPS, "1m": RF24_1MBPS, "2m": RF24_2MBPS}
MAX_CHANNEL = 83            # 2400 + 83 MHz; higher channels leave the 2400-2483.5 MHz band
DEFAULT_SPI_HZ = 4_000_000  # pyrf24 defaults to 10 MHz; jumper wires to the breakout want less

# The high bit marks a zlib stream. The other 31 bits count packets left.
PAYLOAD_SIZE = 32
HEADER = struct.Struct(">I")
CHUNK_SIZE = PAYLOAD_SIZE - HEADER.size
ZLIB_FLAG = 1 << 31
COUNT_MASK = ZLIB_FLAG - 1
MAX_PACKETS = COUNT_MASK + 1

def setup_radio(address: str, channel: int, pa_level: str = "min",
                data_rate: str = "250k", spi_hz: int = DEFAULT_SPI_HZ) -> RF24 | None:
    radio = RF24(CE_PIN, CSN_PIN, spi_hz)
    if not radio.begin():
        return None

    radio.set_pa_level(PA_LEVELS[pa_level])
    radio.data_rate = DATA_RATES[data_rate]
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
    os.sync()  # the stick may be pulled right after this; don't leave the file in the page cache
    log(f"Saved {size} bytes to {file}")
    return True
