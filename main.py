"""Team C transceiver.

    python main.py --mode qm|sri|mrm|nm --role tx|rx [--usb PATH] [--config FILE]

Settings are merged in this order, later wins:
  1. configs/<mode>.json  - the mode's settings (in git, the same on every box)
  2. config.json          - optional per-box overrides (not in git), e.g. a test channel
  3. --role, --usb        - this run's role and stick folder
The mode comes from --mode, else from "mode" in config.json, else qm.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from mtp.logger import log
from mtp.modes import MODES, run

ROOT = Path(__file__).parent
CONFIGS = ROOT / "configs"
STICK_MOUNT = "/mnt/usb"


def stick(action: str) -> bool:
    """sudo teamc-stick mount|umount: the installed copy (no password where tools/install-stick.sh
    ran), else the repo copy (sudo asks the password)."""
    installed = "/usr/local/sbin/teamc-stick"
    command = [installed] if shutil.which(installed) else ["bash", str(ROOT / "tools" / "teamc-stick")]
    result = subprocess.run(["sudo", *command, action])
    return result.returncode == 0


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def main(argv: list[str] | None = None) -> bool:
    parser = argparse.ArgumentParser(description="MTP F26 Team C transceiver")
    parser.add_argument("--mode", choices=MODES, help="the mode to run (default: config.json, else qm)")
    parser.add_argument("--role", choices=("tx", "rx"),
                        help="tx sends the stick's file (NM: source node); rx receives (NM: relay)")
    parser.add_argument("--usb", help="folder of the stick (default: usb_device in the mode's config)")
    parser.add_argument("--config", type=Path, help="per-box overrides (default: config.json if present)")
    parser.add_argument("--no-mount", action="store_true",
                        help="do not mount / unmount the stick (it is mounted by hand, or not under /mnt/usb)")
    parser.add_argument("--keep-mounted", action="store_true",
                        help="mount if needed, but leave the stick mounted at the end")
    parser.add_argument("--configs", type=Path, default=CONFIGS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    box_path = args.config or ROOT / "config.json"
    box = {}
    if args.config or box_path.exists():
        try:
            box = read_json(box_path)
        except (OSError, ValueError) as error:
            log(f"Cannot read {box_path}: {error}")
            return False

    mode = args.mode or box.get("mode", "qm")
    if mode not in MODES:
        log(f"mode must be one of {', '.join(MODES)} (--mode or config.json)")
        return False

    mode_path = args.configs / f"{mode}.json"
    try:
        config = read_json(mode_path)
    except (OSError, ValueError) as error:
        log(f"Cannot read {mode_path}: {error}")
        return False

    config.update(box)
    config["mode"] = mode
    if args.role:
        config["tx_rx_mode"] = args.role
    if args.usb:
        config["usb_device"] = args.usb

    if config.get("tx_rx_mode") not in ("tx", "rx"):
        log("Say which role this box has: --role tx or --role rx")
        return False

    overrides = sorted(set(box) - {"mode"})
    log(f"Initializing transceiver in {mode.upper()} mode as {config['tx_rx_mode'].upper()} "
        f"({mode_path.name}{', config.json overrides: ' + ', '.join(overrides) if overrides else ''})")

    # The stick: mounted before the mode, unmounted after it (also after a failure or Ctrl+C),
    # so the routine is plug in -> run -> pull out.
    usb = str(config.get("usb_device", ""))
    manage = not args.no_mount and (usb == STICK_MOUNT or usb.startswith(STICK_MOUNT + "/"))
    if manage:
        if not stick("mount"):
            log("No stick mounted: plug one in (or use --no-mount)")
            return False
        Path(usb).mkdir(parents=True, exist_ok=True)   # e.g. /mnt/usb/nm for NM
    try:
        return run(mode, config)
    finally:
        if manage and not args.keep_mounted:
            if stick("umount"):
                log("Stick unmounted: you can pull it out")
            else:
                log("WARNING: could not unmount the stick: run 'sudo teamc-stick umount' before pulling it")


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
