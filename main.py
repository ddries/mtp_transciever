from pathlib import Path

from logger import log
from config import load_config
from usb import read_file_from_usb
from radio import setup_radio, send_file, receive_file

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

    radio = setup_radio(address, channel)
    if not radio:
        log("nRF24L01 is not responding, check the wiring")
        return

    log(f"Radio ready on address {address}, channel {channel}")

    if tx_rx_mode == "tx":
        send_file(radio, file)
    else:
        receive_file(radio, file)

    radio.power = False

main()