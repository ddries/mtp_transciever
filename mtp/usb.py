from pathlib import Path

# Files that macOS and Windows leave on a stick: ".DS_Store", "._x", Office lock files "~$x",
# Word temp files "~WRLxxxx.tmp", "desktop.ini", "Thumbs.db".
SYSTEM_FILES = ("desktop.ini", "thumbs.db")
DEFAULT_OUTPUT = "output.txt"


def output_path(dev: str, name: str | None = None) -> Path | None:
    """Where the receiver writes: <stick>/<name>, a plain file name (default output.txt)."""
    name = name or DEFAULT_OUTPUT
    if "/" in name or "\\" in name or name in (".", "..") or name.startswith("."):
        return None
    return Path(dev) / name

def read_file_from_usb(dev: str) -> Path | None:
    path = Path(dev)

    if not path.is_dir():
        return None

    files = sorted(
        entry for entry in path.iterdir()
        if entry.is_file()
        and not entry.name.startswith((".", "~"))
        and entry.name.lower() not in SYSTEM_FILES
    )

    if not files:
        return None

    # The file to send is a .txt; with several, take the largest
    txt = [entry for entry in files if entry.suffix.lower() == ".txt"]
    if txt:
        return max(txt, key=lambda entry: entry.stat().st_size)

    return files[0]
