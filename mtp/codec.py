import os
import tempfile
import zlib
from pathlib import Path


def encode_payload(data: bytes, compression: bool) -> tuple[bytes, bool]:
    """With compression on, always send a zlib stream: its Adler-32 lets the receiver reject a
    corrupted, truncated or spliced file. Data that does not shrink goes as stored blocks
    (level 0, 11 bytes more). Raw is only for compression off (old receivers)."""
    if not compression:
        return data, False
    encoded = zlib.compress(data, 6)
    if len(encoded) >= len(data):
        encoded = zlib.compress(data, 0)
    return encoded, True


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
            output.flush()
            os.fsync(output.fileno())  # the data is on the stick before the rename makes it visible
        pending.replace(file)
    return size
