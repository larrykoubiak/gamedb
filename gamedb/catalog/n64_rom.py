"""Read N64 cartridge images in their native and copier byte orders."""

from array import array


N64_ROM_LIMIT = 64 * 1024 * 1024
Z64_MAGIC = b"\x80\x37\x12\x40"
V64_MAGIC = b"\x37\x80\x40\x12"
N64_MAGIC = b"\x40\x12\x37\x80"
N64_LAYOUTS = ("z64", "v64", "n64")


def swap_words(content, *, width=2):
    words = array({2: "H", 4: "I"}[width])
    words.frombytes(content)
    words.byteswap()
    return words.tobytes()


def big_endian(content):
    magic = content[:4]
    if magic == Z64_MAGIC:
        return content
    if magic == V64_MAGIC:
        return swap_words(content)
    if magic == N64_MAGIC:
        return swap_words(content, width=4)
    raise ValueError("Unknown Nintendo 64 ROM byte order")


def rom_byte_order(content, layout):
    native = big_endian(content)
    if layout == "z64":
        return native
    return swap_words(native, width={"v64": 2, "n64": 4}[layout])
