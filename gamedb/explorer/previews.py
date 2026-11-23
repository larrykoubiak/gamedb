"""Persistent WebP previews of the originals served by the Explorer."""
from functools import lru_cache
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading

from PIL import Image, ImageOps

from gamedb.config import PROJECT_ROOT


def source_revision(stat):
    return f"{stat.st_mtime_ns:x}-{stat.st_ctime_ns:x}-{stat.st_size:x}"


def _preview_source(source, size, page):
    if source.suffix.lower() == ".pdf":
        try:
            number = str(page)
            rendered = subprocess.run(
                ["pdftoppm", "-f", number, "-l", number, "-singlefile", "-scale-to", str(size), "-png", str(source)],
                check=True, capture_output=True, timeout=20,
            ).stdout
        except subprocess.SubprocessError as error:
            raise ValueError("Could not render the manual page") from error
        return Image.open(BytesIO(rendered), formats=("PNG",))
    return Image.open(source, formats=("PNG", "JPEG"))


class ArtworkPreviewCache:
    VERSION = "v1"
    SIZES = (128, 320)
    MANUAL_PAGE_SIZE = 1600

    def __init__(self, root):
        self.root = Path(root) / self.VERSION
        self.locks = [threading.Lock() for _ in range(64)]
        self.encoders = threading.BoundedSemaphore(3)

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("GAMEDB_PREVIEW_CACHE") or PROJECT_ROOT / "data/media/previews")

    @lru_cache(maxsize=256)
    def manual_pages(self, source: Path, revision):
        """Return page sizes in PDF order for the given file revision."""
        with self.encoders:
            try:
                output = subprocess.run(
                    ["pdfinfo", "-f", "1", "-l", "2147483647", str(source)],
                    check=True, capture_output=True, encoding="utf-8", errors="replace",
                    env={**os.environ, "LC_ALL": "C"}, timeout=20,
                ).stdout
            except subprocess.SubprocessError as error:
                raise ValueError("Could not read the manual pages") from error
        count = re.search(r"^Pages:[ \t]+(\d+)$", output, re.MULTILINE)
        pages = []
        for _, width, height, rotation in re.findall(
            r"^Page[ \t]+(\d+) size:[ \t]+([\d.]+) x ([\d.]+) pts[^\n]*\n"
            r"Page[ \t]+\1 rot:[ \t]+(-?\d+)", output, re.MULTILINE,
        ):
            w, h = float(width), float(height)
            pages.append((h, w) if int(rotation) % 180 else (w, h))
        if not count or not pages or len(pages) != int(count[1]) or any(min(size) <= 0 for size in pages):
            raise ValueError("Could not read the manual pages")
        return tuple(pages)

    def path_for(self, source: Path, size: int, revision: str, *, page: int = 1) -> Path:
        source_key = hashlib.sha256(os.fsencode(source.absolute())).hexdigest()
        page_suffix = f"-page-{page}" if page != 1 else ""
        return self.root / source_key[:2] / f"{source_key}-{size}-{revision}{page_suffix}.webp"

    def write_preview(self, target, original, size):
        if original.width * original.height > Image.MAX_IMAGE_PIXELS:
            raise ValueError("Image is too large for a preview")
        original.draft("RGB", (size, size))
        image = original
        if image.has_transparency_data and image.mode != "RGBA":
            image = image.convert("RGBA")
        elif image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        quality = 88 if size == self.MANUAL_PAGE_SIZE else 81
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            try:
                ImageOps.exif_transpose(image).save(temporary, "WEBP", quality=quality, method=4)
                temporary.flush()
                os.replace(temporary.name, target)
            finally:
                Path(temporary.name).unlink(missing_ok=True)

    def get(self, source: Path, size: int, *, page: int = 1) -> Path:
        is_pdf = source.suffix.lower() == ".pdf"
        if size not in self.SIZES and (not is_pdf or size != self.MANUAL_PAGE_SIZE):
            raise ValueError("Unknown preview size")
        if page < 1 or (page != 1 and not is_pdf):
            raise ValueError("Invalid preview page")
        target = self.path_for(source, size, source_revision(source.stat()), page=page)
        if target.is_file():
            return target
        # Facing pages can render in parallel within the encoder limit.
        lock = self.locks[(int(target.parent.name, 16) + page - 1) % len(self.locks)]
        with lock:
            if target.is_file():
                return target
            with self.encoders:
                try:
                    with _preview_source(source, size, page) as original:
                        self.write_preview(target, original, size)
                except Image.DecompressionBombError as error:
                    raise ValueError("Image is too large for a preview") from error
        return target
