"""Apply cartridge translation patches to a verified base ROM in memory."""

from zlib import crc32


MAX_ROM_SIZE = 16 * 1024 * 1024
COPIER_HEADER_SIZE = 512
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
    return ((patch_format == "ips" and layout in ("headerless", "headered"))
            or (patch_format in DELTA_MAGIC and layout == "headerless"))


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


def _apply_ips(source, patch, prefix_size):
    reader = _ips_reader(patch)
    target = bytearray(prefix_size)
    target.extend(source)
    for offset, content in _ips_edits(reader):
        end = offset + len(content)
        if end > MAX_ROM_SIZE + prefix_size:
            raise PatchError("The patched SNES ROM would exceed 16 MiB.")
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


def embedded_input(patch, patch_format):
    try:
        _, source_size, _, source_crc, _ = _delta_header(patch, patch_format)
    except PatchError:
        return None
    return source_size, f"{source_crc:08x}"


def _apply_delta(source, patch, patch_format):
    reader, source_size, target_size, source_crc, target_crc = _delta_header(patch, patch_format)
    if source_size != len(source) or crc32(source) != source_crc:
        raise PatchError("The patch expects a different base ROM checksum or size.")
    if not 0 < target_size <= MAX_ROM_SIZE:
        raise PatchError("The patch declares an invalid SNES ROM size.")
    apply = _apply_bps if patch_format == "bps" else _apply_ups
    target = apply(source, reader, target_size)
    if reader.remaining:
        raise PatchError("Unexpected data after the patch commands.")
    if crc32(target) != target_crc:
        raise PatchError("The patched ROM checksum does not match.")
    return target


def apply_translation(source, patch, patch_format, layout):
    if not supports_patching(patch_format, layout):
        raise PatchError("The patch requires an unsupported input layout.")
    if not 0 < len(source) <= MAX_ROM_SIZE:
        raise PatchError("Invalid SNES base ROM size.")
    if patch_format == "ips":
        prefix_size = COPIER_HEADER_SIZE if layout == "headered" else 0
        return _apply_ips(source, patch, prefix_size)
    return _apply_delta(source, patch, patch_format)
