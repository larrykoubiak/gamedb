"""Apply cartridge translation patches to a verified base ROM in memory."""

from io import BytesIO
import os
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen
from tempfile import TemporaryDirectory
from threading import Timer
from zlib import crc32

from gamedb.catalog.n64_rom import N64_LAYOUTS, N64_ROM_LIMIT, big_endian, rom_byte_order
from gamedb.catalog.nes_rom import INES_HEADER_SIZE, ines_boundaries


MAX_ROM_SIZE = 16 * 1024 * 1024
COPIER_HEADER_SIZE = 512
N64_DISK_LAYOUT = "ndd"
N64_DISK_SIZE = 64_931_840
DELTA_MAGIC = {"bps": b"BPS1", "ups": b"UPS1"}


class PatchError(ValueError):
    """The patch cannot produce a verified result for this input."""


class _PatchReader:
    def __init__(self, data, offset, end):
        self.data = memoryview(data)
        self.offset = offset
        self.end = end

    @property
    def remaining(self):
        return self.end - self.offset

    def take(self, size):
        start = self.offset
        if size > self.remaining:
            raise PatchError("The patch is truncated.")
        self.offset += size
        return self.data[start:self.offset]

    def byte(self):
        if self.offset == self.end:
            raise PatchError("The patch is truncated.")
        value = self.data[self.offset]
        self.offset += 1
        return value

    def number(self):
        # BPS and UPS use a biased base-128 integer with a final high bit.
        value, shift = 0, 1
        for _ in range(8):
            byte = self.byte()
            value += (byte & 0x7f) * shift
            if byte & 0x80:
                return value
            shift <<= 7
            value += shift
        raise PatchError("Invalid patch number.")

    def delta(self):
        value = self.number()
        return -(value >> 1) if value & 1 else value >> 1


def supports_patching(patch_format, layout):
    if layout == N64_DISK_LAYOUT:
        return patch_format == "ppf"
    if layout in N64_LAYOUTS:
        return patch_format in {"bps", "ips", "ups", "xdelta"}
    return ((patch_format == "ips" and layout in ("headerless", "headered", "ines", "ines-payload"))
            or (patch_format in DELTA_MAGIC and layout in ("headerless", "ines", "ines-payload")))


def _ips_reader(patch):
    if patch[:5] != b"PATCH":
        raise PatchError("Invalid IPS header.")
    return _PatchReader(patch, 5, len(patch))


def _ips_edits(reader):
    while (address := reader.take(3)) != b"EOF":
        length = int.from_bytes(reader.take(2), "big")
        if length:
            content = reader.take(length)
        else:
            length = int.from_bytes(reader.take(2), "big")
            content = bytes(reader.take(1)) * length
            if not length:
                raise PatchError("Invalid IPS repeat length.")
        yield int.from_bytes(address, "big"), content
    if reader.remaining not in (0, 3):
        raise PatchError("Unexpected data after the IPS terminator.")


def valid_ips(patch):
    try:
        for _ in _ips_edits(_ips_reader(patch)):
            pass
    except PatchError:
        return False
    return True


def _apply_ips(source, patch, prefix_size, max_rom_size):
    reader = _ips_reader(patch)
    target = bytearray(prefix_size)
    target.extend(source)
    for offset, content in _ips_edits(reader):
        end = offset + len(content)
        if end > max_rom_size + prefix_size:
            raise PatchError(f"The patched ROM would exceed {max_rom_size // (1024 * 1024)} MiB.")
        if end > len(target):
            target.extend(bytes(end - len(target)))
        target[offset:end] = content
    if reader.remaining == 3:
        del target[int.from_bytes(reader.take(3), "big"):]
    if len(target) <= prefix_size:
        raise PatchError("The patch produced an empty ROM.")
    return target[prefix_size:]


def _apply_bps(source, reader, target_size):
    reader.take(reader.number())  # Metadata before the action stream.
    target = bytearray()
    source_offset = target_offset = 0
    while len(target) < target_size:
        instruction = reader.number()
        action, length = instruction & 3, (instruction >> 2) + 1
        if len(target) + length > target_size:
            raise PatchError("A BPS command exceeds the target size.")
        if action == 0:
            start = len(target)
            if start + length > len(source):
                raise PatchError("A BPS read exceeds the base ROM size.")
            target.extend(source[start:start + length])
        elif action == 1:
            target.extend(reader.take(length))
        elif action == 2:
            source_offset += reader.delta()
            end = source_offset + length
            if not 0 <= source_offset < end <= len(source):
                raise PatchError("A BPS copy exceeds the base ROM size.")
            target.extend(source[source_offset:end])
            source_offset = end
        else:
            target_offset += reader.delta()
            if not 0 <= target_offset < len(target):
                raise PatchError("A BPS copy refers to data outside the completed output.")
            # Each byte produced by an overlapping copy is available to the next read.
            span = target[target_offset:target_offset + length]
            copies, remainder = divmod(length, len(span))
            target.extend(span * copies)
            target.extend(span[:remainder])
            target_offset += length
    return target


def _apply_ups(source, reader, target_size):
    # A shrinking UPS patch can include XOR edits in the tail that it discards.
    target = bytearray(source)
    if len(target) < target_size:
        target.extend(bytes(target_size - len(target)))
    offset = 0
    while reader.remaining:
        offset += reader.number()
        while difference := reader.byte():
            if offset >= len(target):
                raise PatchError("A UPS edit is outside the ROM.")
            target[offset] ^= difference
            offset += 1
        offset += 1
    del target[target_size:]
    return target


def _delta_header(patch, patch_format):
    if len(patch) < 18 or patch[:4] != DELTA_MAGIC[patch_format]:
        raise PatchError("Invalid patch header.")
    source_crc, target_crc, patch_crc = (
        int.from_bytes(patch[offset:offset + 4], "little")
        for offset in range(len(patch) - 12, len(patch), 4)
    )
    if crc32(memoryview(patch)[:-4]) != patch_crc:
        raise PatchError("The patch checksum does not match.")
    reader = _PatchReader(patch, 4, len(patch) - 12)
    source_size, target_size = reader.number(), reader.number()
    return reader, source_size, target_size, source_crc, target_crc


def embedded_input(patch, patch_format, *, same_size=False):
    try:
        _, source_size, target_size, source_crc, _ = _delta_header(patch, patch_format)
    except PatchError:
        return None
    if same_size and source_size != target_size:
        return None
    return source_size, f"{source_crc:08x}"


def _apply_delta(source, patch, patch_format, max_rom_size):
    reader, source_size, target_size, source_crc, target_crc = _delta_header(patch, patch_format)
    if source_size != len(source) or crc32(source) != source_crc:
        raise PatchError("The patch expects a different base ROM checksum or size.")
    if not 0 < target_size <= max_rom_size:
        raise PatchError("The patch declares an invalid ROM size.")
    apply = _apply_bps if patch_format == "bps" else _apply_ups
    target = apply(source, reader, target_size)
    if reader.remaining:
        raise PatchError("Unexpected data after the patch commands.")
    if crc32(target) != target_crc:
        raise PatchError("The patched ROM checksum does not match.")
    return target


def _apply_xdelta(source, patch, max_rom_size):
    if patch[:4] != b"\xd6\xc3\xc4\x00":
        raise PatchError("Expected a VCDIFF patch.")
    env = {key: value for key, value in os.environ.items() if key != "XDELTA"}
    try:
        with TemporaryDirectory(prefix="gamedb-xdelta-") as directory:
            Path(directory, "base.rom").write_bytes(source)
            Path(directory, "patch.vcdiff").write_bytes(patch)
            # Disable external decompression and recompression. Bound the decoded stream.
            command = ["xdelta3", "-d", "-D", "-R", "-c", "-s", "base.rom", "patch.vcdiff"]
            with Popen(command, cwd=directory, env=env, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL) as decoder:
                timeout = Timer(30, decoder.kill)
                timeout.start()
                try:
                    result = decoder.stdout.read(max_rom_size + 1)
                    if len(result) > max_rom_size:
                        decoder.kill()
                        raise PatchError("The patched ROM exceeds the size limit.")
                    if decoder.wait() != 0 or not result:
                        raise PatchError("xdelta3 could not decode this patch with the verified base ROM.")
                finally:
                    timeout.cancel()
    except OSError as error:
        raise PatchError("The xdelta3 decoder is unavailable.") from error
    return result


def _ines_program(data):
    try:
        start, _, end = ines_boundaries(data)
    except ValueError as error:
        raise PatchError("Invalid iNES program or graphics data.") from error
    if end != len(data):
        raise PatchError("The iNES header and image size do not agree.")
    return start


def apply_ppf3(image, delta, size):
    header = delta.read(60)
    if len(header) != 60 or not header.startswith(b"PPF30\x02"):
        raise PatchError("Expected a PPF3 patch")
    image_type, block_check, undo = header[56:59]
    if image_type != 0 or block_check not in (0, 1) or undo not in (0, 1):
        raise PatchError("Unsupported PPF3 image type or flags")
    if block_check:
        block = delta.read(1024)
        image.seek(0x9320)
        if len(block) != 1024 or image.read(1024) != block:
            raise PatchError("PPF3 source block does not match")
    while record := delta.read(9):
        if len(record) != 9:
            raise PatchError("Incomplete PPF3 record")
        offset = int.from_bytes(record[:8], "little")
        length = record[8]
        data = delta.read(length * (1 + undo))
        if not length or len(data) != length * (1 + undo) or offset + length > size:
            raise PatchError("Invalid PPF3 edit")
        image.seek(offset)
        image.write(data[:length])


def apply_translation(source, patch, patch_format, layout, *, pad_to_size=None, output_header=None):
    if not supports_patching(patch_format, layout):
        raise PatchError("The patch requires an unsupported input layout.")
    if layout == N64_DISK_LAYOUT:
        if len(source) != N64_DISK_SIZE or pad_to_size is not None or output_header is not None:
            raise PatchError("The patch requires a 64DD SDK disk image.")
        with BytesIO(source) as disk, BytesIO(patch) as delta:
            apply_ppf3(disk, delta, len(source))
            return disk.getvalue()
    nintendo64 = layout in N64_LAYOUTS
    max_rom_size = N64_ROM_LIMIT if nintendo64 else MAX_ROM_SIZE
    if not 0 < len(source) <= max_rom_size:
        raise PatchError("Invalid base ROM size.")
    if pad_to_size is not None:
        if (patch_format != "ips" or layout != "headerless" or type(pad_to_size) is not int
                or not len(source) <= pad_to_size <= MAX_ROM_SIZE):
            raise PatchError("The patch requires an invalid padded ROM size.")
        source = source.ljust(pad_to_size, b"\x00")
    if layout == "ines-payload":
        if _ines_program(source) != INES_HEADER_SIZE:
            raise PatchError("The patch requires a standard 16-byte iNES header.")
        header, source = source[:INES_HEADER_SIZE], source[INES_HEADER_SIZE:]
    if nintendo64:
        try:
            source = rom_byte_order(source, layout)
        except ValueError as error:
            raise PatchError("Invalid Nintendo 64 base ROM.") from error
    if patch_format == "ips":
        prefix_size = COPIER_HEADER_SIZE if layout == "headered" else 0
        result = _apply_ips(source, patch, prefix_size, max_rom_size)
    elif patch_format == "xdelta":
        result = _apply_xdelta(source, patch, max_rom_size)
    else:
        result = _apply_delta(source, patch, patch_format, max_rom_size)
    if layout == "ines-payload":
        result = bytearray(header) + result
    if output_header is not None:
        if (layout not in ("ines", "ines-payload") or len(output_header) != INES_HEADER_SIZE
                or _ines_program(result) != INES_HEADER_SIZE):
            raise PatchError("The patch requires a different iNES output header.")
        result[:INES_HEADER_SIZE] = output_header
    if layout in ("ines", "ines-payload"):
        _ines_program(result)
    if nintendo64:
        try:
            if len(result) < 64 or len(result) % 4:
                raise ValueError("Invalid cartridge length")
            result = big_endian(result)
        except ValueError as error:
            raise PatchError("The patch did not produce a valid Nintendo 64 ROM.") from error
    return result
