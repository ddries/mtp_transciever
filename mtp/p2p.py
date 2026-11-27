"""Point-to-point file transfer (QM, SRI, MRM): one transmitter reads the stick, one receiver
writes output.txt. Enhanced ShockBurst with hardware ACK; see README.md for the packet format."""

import os
import struct
import time
import zlib
from pathlib import Path

from pyrf24 import (RF24, RF24_PA_MIN, RF24_PA_LOW, RF24_PA_HIGH, RF24_PA_MAX,
                    RF24_250KBPS, RF24_1MBPS, RF24_2MBPS)

from .codec import encode_payload, save_payload
from .hardware import CE_PIN, CSN_PIN, DEFAULT_SPI_HZ, LEGAL_FIXED_CHANNEL_PA, MAX_CHANNEL
from .logger import log
from .usb import output_path, read_file_from_usb

# Timing. The radio ACKs each packet in hardware (15 retries, 1.5 ms apart); on top of that the
# transmitter keeps trying one packet until SEND_TIMEOUT_S, so a person walking between the boxes
# does not end the transfer. The receiver gives up after RECEIVE_TIMEOUT_S without a valid packet
# (longer than SEND_TIMEOUT_S, so it never quits first), and after the last packet it keeps
# listening for LINGER_S so the hardware can ACK a retransmission of it.
SEND_TIMEOUT_S = 30.0
RECEIVE_TIMEOUT_S = 35.0
LINGER_S = 0.5

PA_LEVELS = {"min": RF24_PA_MIN, "low": RF24_PA_LOW, "high": RF24_PA_HIGH, "max": RF24_PA_MAX}
DATA_RATES = {"250k": RF24_250KBPS, "1m": RF24_1MBPS, "2m": RF24_2MBPS}

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
    deadline = time.monotonic() + SEND_TIMEOUT_S
    while True:
        if radio.write(packet):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)

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
    last_valid = 0.0
    while expected is None or expected >= 0:
        if not radio.available():
            # Before the first packet wait as long as needed; after it, a transmitter that gave up
            # or a packet we could not accept must not leave us waiting forever.
            if expected is not None and time.monotonic() - last_valid > RECEIVE_TIMEOUT_S:
                log(f"No valid packet for {RECEIVE_TIMEOUT_S:.0f} s with {expected + 1} packets "
                    "missing, giving up")
                radio.stop_listening()
                return False
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
        last_valid = time.monotonic()

    # If the ACK of the last packet was lost the transmitter sends it again: stay in RX mode for a
    # moment so the hardware ACKs it, and drop the copies.
    linger_end = time.monotonic() + LINGER_S
    while time.monotonic() < linger_end:
        if radio.available():
            radio.read(radio.get_dynamic_payload_size())
    radio.stop_listening()
    try:
        size = save_payload(file, data, compressed)
    except (OSError, ValueError, zlib.error) as error:
        log(f"Failed to save received file: {error}")
        return False
    os.sync()  # the stick may be pulled right after this; don't leave the file in the page cache
    log(f"Saved {size} bytes to {file}")
    return True

def run(config: dict, profile: dict, name: str) -> bool:
    """One transfer with the mode's radio profile; keys in config.json override the profile."""
    settings = {**profile, **{k: config[k] for k in profile if k in config}}

    usb_device = config.get("usb_device", "")
    if not usb_device:
        log("USB device is required in config.json")
        return False

    tx_rx_mode = config.get("tx_rx_mode", "")
    if tx_rx_mode not in ("tx", "rx"):
        log("tx_rx_mode must be tx or rx in config.json")
        return False

    address = config.get("address", "")
    if len(address) != 5:
        log("A 5 character address is required in config.json")
        return False

    channel = settings["channel"]
    if not isinstance(channel, int) or not 0 <= channel <= MAX_CHANNEL:
        log(f"channel must be 0-{MAX_CHANNEL} (2400-{2400 + MAX_CHANNEL} MHz)")
        return False

    pa_level = settings["pa_level"]
    if pa_level not in PA_LEVELS:
        log(f"pa_level must be one of {', '.join(PA_LEVELS)}")
        return False
    if pa_level != LEGAL_FIXED_CHANNEL_PA:
        log(f"WARNING: pa_level {pa_level} is over 10 mW e.i.r.p. with the SP4 on a fixed channel: "
            "use it only into an attenuator")

    data_rate = settings["data_rate"]
    if data_rate not in DATA_RATES:
        log(f"data_rate must be one of {', '.join(DATA_RATES)}")
        return False

    compression = config.get("compression", True)
    if not isinstance(compression, bool):
        log("compression must be true or false (without quotes) in config.json")
        return False

    spi_hz = config.get("spi_hz", DEFAULT_SPI_HZ)

    log(f"{name}: {tx_rx_mode.upper()} with USB device {usb_device}")

    if tx_rx_mode == "tx":
        # The largest .txt on the stick (usb.py skips Windows/macOS leftovers)
        file = read_file_from_usb(usb_device)
        if not file:
            log("The given USB device is empty")
            return False
        log(f"Successfully read file {file.name} ({file.stat().st_size} bytes)")
    else:
        file = output_path(usb_device, config.get("output_name"))
        if file is None:
            log("output_name must be a plain file name, e.g. test_sri.txt")
            return False

    radio = setup_radio(address, channel, pa_level, data_rate, spi_hz)
    if not radio:
        log("nRF24L01 is not responding, check the wiring")
        return False

    log(f"Radio ready on address {address}, channel {channel}, {data_rate}bps, "
        f"PA {pa_level}, SPI {spi_hz // 1000} kHz")

    try:
        if tx_rx_mode == "tx":
            return send_file(radio, file, compression=compression)
        return receive_file(radio, file)
    finally:
        radio.power = False
