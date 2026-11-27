"""Network Mode: NMP-1 (Sofia's code in nmp.py / radio.py / main.py, see README.md here).

Every node runs the same program; the source node ("tx_rx_mode": "tx") loads the stick's file,
the others start empty. GO at start, STOP with Ctrl+C or SIGTERM: STOP writes output.txt to the
stick if the copy is complete and its CRC-32 checks. NMP-1 fixes the radio profile (channel 79,
1 Mbps, no auto-ACK); only the PA level comes from config.json, and on one fixed channel the SP4
is legal only at "min" (10 mW e.i.r.p.).
"""

from pathlib import Path

from ...hardware import CE_PIN, CSN_PIN, DEFAULT_SPI_HZ, LEGAL_FIXED_CHANNEL_PA, PA_NAMES
from ...logger import log
from ...usb import read_file_from_usb


def arguments(config: dict) -> list[str] | None:
    """config.json -> the command line of nm/main.py, or None if the config is wrong."""
    usb_device = config.get("usb_device", "")
    if not usb_device or not Path(usb_device).is_dir():
        log("NM: usb_device must be a mounted folder in config.json")
        return None
    pa_level = config.get("pa_level", LEGAL_FIXED_CHANNEL_PA)
    if pa_level not in PA_NAMES:
        log(f"pa_level must be one of {', '.join(PA_NAMES)}")
        return None
    if pa_level != LEGAL_FIXED_CHANNEL_PA:
        log(f"WARNING: NM pa_level {pa_level} is over 10 mW e.i.r.p. on its fixed channel")

    argv = ["--radio", "nrf24", "--ce", str(CE_PIN), "--csn", str(CSN_PIN), "--pa", pa_level,
            "--spi-hz", str(config.get("spi_hz", DEFAULT_SPI_HZ)),
            "--output", str(Path(usb_device) / "output.txt"), "--go"]
    if config.get("tx_rx_mode") == "tx":
        file = read_file_from_usb(usb_device)
        if not file:
            log("NM: the source node needs a file on the stick")
            return None
        argv += ["--input", str(file)]
        log(f"NM: source node, file {file.name} ({file.stat().st_size} bytes)")
    else:
        log("NM: relay node, starts without the file")
    return argv


def run(config: dict) -> bool:
    argv = arguments(config)
    if argv is None:
        return False
    from . import main  # NMP-1 loop; pyrf24 loads here
    return main.main(argv) == 0
