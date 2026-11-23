"""Read and fingerprint the PRG and CHR bytes in verified iNES archives."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import md5, sha1
import json
from zlib import crc32

from gamedb.catalog.cartridges import read_verified_rom
from gamedb.catalog.retail import write_report


INES_HEADER_SIZE = 16


def _rom_size(low, high, banksize):
    if high == 15:
        return (1 << (low >> 2)) * (2 * (low & 3) + 1)
    return (low | (high << 8)) * banksize


def ines_boundaries(data):
    """Return program start and program/graphics ends for iNES or NES 2.0."""
    if len(data) < INES_HEADER_SIZE or data[:4] != b"NES\x1a":
        raise ValueError("Invalid iNES header")
    sizes = data[9] if data[7] & 0x0c == 8 else 0
    prg_size = _rom_size(data[4], sizes & 15, 16 * 1024)
    chr_size = _rom_size(data[5], sizes >> 4, 8 * 1024)
    start = INES_HEADER_SIZE + (512 if data[6] & 4 else 0)
    end = start + prg_size + chr_size
    if not prg_size or end > len(data):
        raise ValueError("Incomplete iNES program or graphics data")
    return start, start + prg_size, end


def _fingerprint(rom):
    data = read_verified_rom(rom)
    if data is None:
        return None
    try:
        start, chr_start, end = ines_boundaries(data)
    except ValueError:
        return None
    view = memoryview(data)
    result = {
        "prg": sha1(view[start:chr_start]).hexdigest(),
        "chr": sha1(view[chr_start:end]).hexdigest() if end > chr_start else "",
    }
    if start == INES_HEADER_SIZE and end == len(data):
        payload = view[start:end]
        result["withoutHeader"] = {"sha1": sha1(payload).hexdigest(), "md5": md5(payload).hexdigest(),
                                   "crc32": f"{crc32(payload):08x}", "size": len(payload)}
    return result


def ines_fingerprints(path, roms):
    cached = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    pending = {rom.sha1: rom for rom in roms if rom.sha1 not in cached}
    if pending:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for digest, value in zip(pending, pool.map(_fingerprint, pending.values()), strict=True):
                if value is not None:
                    cached[digest] = value
        write_report(path, cached)
    return cached
