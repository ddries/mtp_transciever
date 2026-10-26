from pathlib import Path

def read_file_from_usb(dev: str) -> Path | None:
    path = Path(dev)

    if not path.is_dir():
        return None

    # skip hidden files, e.g., .DS_Store
    files = sorted(
        entry for entry in path.iterdir()
        if entry.is_file() and not entry.name.startswith(".")
    )

    if not files:
        return None

    return files[0]
