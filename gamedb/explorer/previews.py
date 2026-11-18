"""Persistent WebP previews of the originals served by the Explorer."""
import hashlib
import os
from pathlib import Path
import tempfile
import threading

from PIL import Image, ImageOps


class ArtworkPreviewCache:
    VERSION = "v1"
    SIZES = (128, 320)

    def __init__(self, root):
        self.root = Path(root) / self.VERSION
        self.locks = [threading.Lock() for _ in range(64)]
        self.encoders = threading.BoundedSemaphore(3)

    def get(self, source: Path, size: int) -> Path:
        if size not in self.SIZES:
            raise ValueError("Unknown preview size")
        source_key = hashlib.sha256(os.fsencode(source.absolute())).hexdigest()
        directory = self.root / source_key[:2]
        stat = source.stat()
        revision = f"{stat.st_mtime_ns:x}-{stat.st_ctime_ns:x}-{stat.st_size:x}"
        target = directory / f"{source_key}-{size}-{revision}.webp"
        if target.is_file():
            return target
        lock = self.locks[int(source_key[:2], 16) % len(self.locks)]
        with lock:
            if target.is_file():
                return target
            directory.mkdir(parents=True, exist_ok=True)
            with self.encoders, tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
                try:
                    with Image.open(source, formats=("PNG", "JPEG")) as original:
                        if original.width * original.height > Image.MAX_IMAGE_PIXELS:
                            raise ValueError("Image is too large for a preview")
                        original.draft("RGB", (size, size))
                        image = original
                        if image.has_transparency_data and image.mode != "RGBA":
                            image = image.convert("RGBA")
                        elif image.mode not in ("RGB", "RGBA"):
                            image = image.convert("RGB")
                        image.thumbnail((size, size), Image.Resampling.LANCZOS)
                        ImageOps.exif_transpose(image).save(temporary, "WEBP", quality=81, method=4)
                    temporary.flush()
                    os.replace(temporary.name, target)
                except Image.DecompressionBombError as error:
                    raise ValueError("Image is too large for a preview") from error
                finally:
                    Path(temporary.name).unlink(missing_ok=True)
        return target
