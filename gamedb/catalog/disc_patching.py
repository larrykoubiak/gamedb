"""Apply binary disc patches to temporary, verified images."""

import os
from shutil import copyfile
import subprocess

from .patching import PatchError


RAW_CD_SECTOR_SIZE = 2352
XDELTA_EXTENSIONS = {".xdelta", ".xdelta3", ".vcdiff"}
DISC_PATCH_EXTENSIONS = XDELTA_EXTENSIONS | {".ppf"}


def _apply_ppf3(image, patch):
    size = image.stat().st_size
    with image.open("r+b") as disc, patch.open("rb") as delta:
        header = delta.read(60)
        if len(header) != 60 or not header.startswith(b"PPF30\x02"):
            raise PatchError("Expected a PPF3 patch")
        image_type, block_check, undo = header[56:59]
        if image_type != 0 or block_check not in (0, 1) or undo not in (0, 1):
            raise PatchError("Unsupported PPF3 image type or flags")
        if block_check:
            block = delta.read(1024)
            disc.seek(0x9320)
            if len(block) != 1024 or disc.read(1024) != block:
                raise PatchError("PPF3 source block does not match")
        while record := delta.read(9):
            if len(record) != 9:
                raise PatchError("Incomplete PPF3 record")
            offset = int.from_bytes(record[:8], "little")
            length = record[8]
            data = delta.read(length * (1 + undo))
            if not length or len(data) != length * (1 + undo) or offset + length > size:
                raise PatchError("Invalid PPF3 edit")
            disc.seek(offset)
            disc.write(data[:length])


def patch_disc_image(source, patch, target):
    """Write one forward patch to a separate raw CD image."""
    extension = patch.suffix.lower()
    if extension in XDELTA_EXTENSIONS:
        try:
            subprocess.run(["xdelta3", "-d", "-D", "-R", "-s", str(source), str(patch), str(target)],
                           check=True, capture_output=True, timeout=300,
                           env={key: value for key, value in os.environ.items() if key != "XDELTA"})
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode(errors="replace").strip()
            raise PatchError(detail or "xdelta3 could not decode the disc patch") from error
        except subprocess.TimeoutExpired as error:
            raise PatchError("xdelta3 timed out on the disc patch") from error
    elif extension == ".ppf":
        copyfile(source, target)
        _apply_ppf3(target, patch)
    else:
        raise PatchError(f"Unsupported disc patch {extension}")
    size = target.stat().st_size
    if not size or size % RAW_CD_SECTOR_SIZE:
        raise PatchError("Patched image does not contain complete raw CD sectors")
