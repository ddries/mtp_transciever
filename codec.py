import tempfile
import zlib
from pathlib import Path


def encode_payload(data: bytes, compression: bool) -> tuple[bytes, bool]:
    if compression and data:
        encoded = zlib.compress(data)
        if len(encoded) < len(data):
            return encoded, True
    return data, False


def save_payload(file: Path, payload: bytearray, compressed: bool) -> int:
    """Publish the recovered file only after the whole payload is validated."""
    with tempfile.TemporaryDirectory(dir=file.parent, prefix=".mtp-") as directory:
        pending = Path(directory) / "received"
        with pending.open("wb") as output:
            if compressed:
                decoder = zlib.decompressobj()
                view = memoryview(payload)
                # Bound each inflate operation on the Pi, even for repetitive input.
                for offset in range(0, len(view), 4096):
                    output.write(decoder.decompress(view[offset:offset + 4096]))
                    if decoder.unused_data:
                        raise ValueError("trailing bytes after the zlib stream")
                if not decoder.eof:
                    raise ValueError("incomplete zlib stream")
            else:
                output.write(payload)
            size = output.tell()
        pending.replace(file)
    return size
