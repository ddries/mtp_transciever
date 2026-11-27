from pathlib import Path

from logger import log
from config import load_config
from usb import read_file_from_usb
from radio import (setup_radio, send_file, receive_file, PA_LEVELS, DATA_RATES, MAX_CHANNEL,
                   DEFAULT_SPI_HZ)

def main():
    log("Initializing transciever...")
    config = load_config(Path(__file__).parent)

    # Get the USB device from configuration
    usb_device = config.get("usb_device", "")
    if not usb_device:
        log("USB device is required in config.json")
        return

    # Get the TX/RX mode from configuration
    tx_rx_mode = config.get("tx_rx_mode", "")
    if tx_rx_mode not in ("tx", "rx"):
        log("TX/RX mode is required in config.json")
        return

    # Get the radio address from configuration
    address = config.get("address", "")
    if len(address) != 5:
        log("A 5 character address is required in config.json")
        return

    channel = config.get("channel", 76)
    if not isinstance(channel, int) or not 0 <= channel <= MAX_CHANNEL:
        log(f"channel must be 0-{MAX_CHANNEL} (2400-{2400 + MAX_CHANNEL} MHz)")
        return

    pa_level = config.get("pa_level", "min")
    if pa_level not in PA_LEVELS:
        log(f"pa_level must be one of {', '.join(PA_LEVELS)}")
        return
    if pa_level != "min":
        log(f"WARNING: pa_level {pa_level} is over 10 mW e.i.r.p. with the SP4: "
            "use it only into an attenuator")

    data_rate = config.get("data_rate", "250k")
    if data_rate not in DATA_RATES:
        log(f"data_rate must be one of {', '.join(DATA_RATES)}")
        return

    spi_hz = config.get("spi_hz", DEFAULT_SPI_HZ)

    log(f"Requested USB device {usb_device}")

    # File to be read from USB if TX, or output file name otherwise    
    file = "output.txt"
    if (tx_rx_mode == "tx"):
        # Get the file from the USB, or the first one if there are more than one 
        file = read_file_from_usb(usb_device)
        if not file:
            log("The given USB device is empty")
            return

        md = file.stat()
        log(f"Succesfully read file {file.name} ({md.st_size} bytes)")
    else:
        file = Path(usb_device) / file

    radio = setup_radio(address, channel, pa_level, data_rate, spi_hz)
    if not radio:
        log("nRF24L01 is not responding, check the wiring")
        return

    log(f"Radio ready on address {address}, channel {channel}, {data_rate}bps, "
        f"PA {pa_level}, SPI {spi_hz // 1000} kHz")

    try:
        if tx_rx_mode == "tx":
            return send_file(radio, file, compression=config.get("compression", True))
        return receive_file(radio, file)
    finally:
        radio.power = False

if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
