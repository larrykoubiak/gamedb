"""Apply binary disc patches to temporary, verified images."""

from contextlib import nullcontext
from mmap import mmap
import os
from shutil import copyfile
import subprocess
from zlib import crc32

from .patching import PatchError, _delta_header, _ips_edits, _ips_reader


RAW_CD_SECTOR_SIZE = 2352
MODE1_USER_DATA_SIZE = 2048
XDELTA_EXTENSIONS = {".xdelta", ".xdelta3", ".vcdiff"}
DISC_PATCH_EXTENSIONS = XDELTA_EXTENSIONS | {".ppf", ".ips", ".ups"}
CD_SYNC = bytes.fromhex("00 ff ff ff ff ff ff ff ff ff ff 00")
XA_CHECKSUM_OFFSET = 2072


def _crc_table_entry(value):
    for _ in range(8):
        value = (value >> 1) ^ (0xD8018001 if value & 1 else 0)
    return value


CD_CRC_TABLE = tuple(_crc_table_entry(value) for value in range(256))
GF_DOUBLE = bytes((value << 1) ^ (0x11D if value & 0x80 else 0) for value in range(256))
GF_TRIPLE = bytes(value ^ doubled for value, doubled in enumerate(GF_DOUBLE))
GF_DIVIDE_BY_THREE = bytes(GF_TRIPLE.index(value) for value in range(256))


def _ecc_parity(data, codewords, symbols, start_stride, symbol_stride):
    parity = bytearray(2 * codewords)
    for codeword in range(codewords):
        position = (codeword // 2) * start_stride + codeword % 2
        weighted, unweighted = 0, 0
        for _ in range(symbols):
            value = data[position]
            weighted = GF_DOUBLE[weighted ^ value]
            unweighted ^= value
            position = (position + symbol_stride) % len(data)
        first = GF_DIVIDE_BY_THREE[GF_DOUBLE[weighted] ^ unweighted]
        parity[codeword] = first
        parity[codeword + codewords] = first ^ unweighted
    return bytes(parity)


def _xa_form1_checksums(sector):
    # CD-ROM XA uses a zeroed sector address for ECC. ECMA-130 and ECMA-168 Annex C.
    if (len(sector) != RAW_CD_SECTOR_SIZE or sector[:12] != CD_SYNC or sector[15] != 2
            or sector[18] & 0x20 or sector[16:20] != sector[20:24]):
        raise PatchError("An edited sector is not CD-ROM XA Form 1")
    payload = sector[16:XA_CHECKSUM_OFFSET]
    edc = 0
    for value in payload:
        edc = (edc >> 8) ^ CD_CRC_TABLE[(edc ^ value) & 0xFF]
    checksum = edc.to_bytes(4, "little")
    encoded = b"\x00" * 4 + payload + checksum
    p_parity = _ecc_parity(encoded, 86, 24, 2, 86)
    q_parity = _ecc_parity(encoded + p_parity, 52, 43, 86, 88)
    return checksum + p_parity + q_parity


def repair_xa_form1_checksums(source, target):
    """Recalculate EDC and ECC for edited sectors of a reviewed XA data track."""
    if source.stat().st_size != target.stat().st_size:
        raise PatchError("XA checksum repair requires the original track length")
    with source.open("rb") as original, target.open("r+b") as modified:
        while sector := modified.read(RAW_CD_SECTOR_SIZE):
            if sector == original.read(RAW_CD_SECTOR_SIZE):
                continue
            checksums = _xa_form1_checksums(sector)
            if checksums != sector[XA_CHECKSUM_OFFSET:]:
                modified.seek(-len(checksums), os.SEEK_CUR)
                modified.write(checksums)


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


def extract_mode1_iso(source, target, *, pregap_sectors=0, pregap_target=None):
    """Extract MODE1 user data, optionally writing the pregap separately."""
    with (
        source.open("rb") as original,
        target.open("wb") as cooked,
        (pregap_target.open("wb") if pregap_target is not None else nullcontext(cooked)) as pregap,
    ):
        sector_number = 0
        while block := original.read(512 * RAW_CD_SECTOR_SIZE):
            if len(block) % RAW_CD_SECTOR_SIZE:
                raise PatchError("Incomplete CD sector")
            for offset in range(0, len(block), RAW_CD_SECTOR_SIZE):
                sector = block[offset:offset + RAW_CD_SECTOR_SIZE]
                silence = sector_number < pregap_sectors and not any(sector)
                if not silence and (sector[:12] != CD_SYNC or sector[15] != 1):
                    raise PatchError("Expected a MODE1/2352 data track")
                output = pregap if sector_number < pregap_sectors else cooked
                output.write(sector[16:16 + MODE1_USER_DATA_SIZE])
                sector_number += 1


def _patch_ips(image, data):
    reader = _ips_reader(data)
    size = image.stat().st_size
    with image.open("r+b") as stream:
        for offset, contents in _ips_edits(reader):
            if offset + len(contents) > size:
                raise PatchError("An IPS edit exceeds the disc image")
            stream.seek(offset)
            stream.write(contents)
        if reader.remaining == 3 and int.from_bytes(reader.take(3), "big") != size:
            raise PatchError("The IPS patch changes the disc image size")


def _patch_ups(image, data):
    reader, source_size, target_size, source_crc, target_crc = _delta_header(data, "ups")
    if image.stat().st_size != source_size or source_size != target_size or not source_size:
        raise PatchError("Expected a fixed-size UPS disc patch")
    with image.open("r+b") as stream, mmap(stream.fileno(), 0) as contents:
        if crc32(contents) != source_crc:
            raise PatchError("The UPS base checksum does not match")
        offset = 0
        while reader.remaining:
            offset += reader.number()
            while difference := reader.byte():
                if offset >= target_size:
                    raise PatchError("A UPS edit exceeds the disc image")
                contents[offset] ^= difference
                offset += 1
            offset += 1
        if crc32(contents) != target_crc:
            raise PatchError("The UPS output checksum does not match")


def patch_disc_image(source, patch, target, *, sector_size=RAW_CD_SECTOR_SIZE):
    """Write one forward patch to a separate CD image."""
    extension = patch.suffix.lower()
    if extension in XDELTA_EXTENSIONS:
        try:
            subprocess.run(["xdelta3", "-d", "-D", "-R", "-s", str(source), str(patch), str(target)],
                           check=True, capture_output=True, timeout=300,
                           env={key: value for key, value in os.environ.items() if key != "XDELTA"})
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode(errors="replace").strip()
            raise PatchError(detail or "xdelta3 could not decode the disc patch") from error
        except FileNotFoundError as error:
            raise PatchError("xdelta3 is required to apply the disc patch") from error
        except subprocess.TimeoutExpired as error:
            raise PatchError("xdelta3 timed out on the disc patch") from error
    elif extension == ".ppf":
        copyfile(source, target)
        _apply_ppf3(target, patch)
    elif extension in {".ips", ".ups"}:
        copyfile(source, target)
        apply = _patch_ips if extension == ".ips" else _patch_ups
        apply(target, patch.read_bytes())
    else:
        raise PatchError(f"Unsupported disc patch {extension}")
    size = target.stat().st_size
    if not size or size % sector_size:
        raise PatchError("Patched image does not contain complete CD sectors")
