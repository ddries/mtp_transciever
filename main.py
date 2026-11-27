"""Team C transceiver. Usage: python main.py [--mode qm|sri|mrm|nm] [--config config.json]

The mode comes from --mode, else from "mode" in config.json (default qm). The rest of config.json
(usb_device, tx_rx_mode, address, ...) is shared; see config.example.json and README.md.
"""

import argparse
import json
from pathlib import Path

from mtp.logger import log
from mtp.modes import MODES, run


def main(argv: list[str] | None = None) -> bool:
    parser = argparse.ArgumentParser(description="MTP F26 Team C transceiver")
    parser.add_argument("--mode", choices=MODES, help="overrides \"mode\" in config.json")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config.json")
    args = parser.parse_args(argv)

    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        log(f"Cannot read {args.config}: {error}")
        return False

    mode = args.mode or config.get("mode", "qm")
    if mode not in MODES:
        log(f"mode must be one of {', '.join(MODES)} (config.json or --mode)")
        return False

    log(f"Initializing transceiver in {mode.upper()} mode...")
    return run(mode, config)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
