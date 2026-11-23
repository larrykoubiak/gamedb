"""Read source labels without decoding chiptune audio."""

import re
from collections import defaultdict
from contextlib import closing
from gzip import GzipFile
from struct import unpack_from
from zipfile import BadZipFile
from zlib import error as ZlibError

from .archives import open_vgm_location, packed_locations

PSF_VERSIONS = {"psf": 1, "minipsf": 1, "psf2": 2, "minipsf2": 2}
RELATED_PSF_VERSIONS = {
    "usf": 0x21, "miniusf": 0x21, "gsf": 0x22, "minigsf": 0x22, "snsf": 0x23, "minisnsf": 0x23,
    "2sf": 0x24, "mini2sf": 0x24, "ncsf": 0x25, "minincsf": 0x25,
}
COMPOSER_TAG_FORMATS = {"nsfe", "vgm", "vgz"}
TRACK_TAG_FORMATS = {"spc", "nsf", "sid", "gbs", *COMPOSER_TAG_FORMATS, *PSF_VERSIONS, *RELATED_PSF_VERSIONS}
PSF_FIELDS = {"game": "album", "title": "title", "artist": "artist",
              "year": "year", "copyright": "copyright"}
JAPANESE = re.compile(r"[\u3041-\u30fa\u3400-\u9fff]")
MAX_PSF_TAG_BYTES = 64 * 1024
MAX_COMPOSER_TAG_BYTES = 64 * 1024
MAX_VGZ_TAG_SCAN = 64 * 1024**2


def tag_text(raw):
    raw = raw.split(b"\0", 1)[0].strip()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def psf_text(raw, utf8):
    if utf8:
        return raw.decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            japanese = raw.decode("cp932")
        except UnicodeDecodeError:
            japanese = ""
        if len(JAPANESE.findall(japanese)) >= 2:
            return japanese
        return tag_text(raw)


def psf_tags(stream, version, size):
    header = stream.read(16)
    if len(header) != 16 or header[:4] != b"PSF" + bytes([version]):
        return {}
    reserved, program = unpack_from("<II", header, 4)
    offset = 16 + reserved + program
    if not 5 <= size - offset <= MAX_PSF_TAG_BYTES:
        return {}
    stream.seek(offset)
    if stream.read(5) != b"[TAG]":
        return {}
    fields = {}
    for line in stream.read(MAX_PSF_TAG_BYTES).splitlines():
        key, sep, value = line.partition(b"=")
        key = key.strip().lower()
        value = value.split(b"\0", 1)[0].strip()
        if sep and value and key not in fields:
            fields[key] = value
    return {label: psf_text(fields[key.encode()], fields.get(b"utf8") == b"1")
            for key, label in PSF_FIELDS.items() if key.encode() in fields}


def sid_tags(header):
    if len(header) < 118 or header[:4] not in (b"PSID", b"RSID"):
        return {}
    version, offset = unpack_from(">HH", header, 4)
    first_offset = 118 if version == 1 else 124
    if version not in (1, 2, 3, 4) or offset != first_offset or len(header) < offset:
        return {}
    if header[:4] == b"RSID" and version == 1:
        return {}
    def sid_text(raw):
        return raw.split(b"\0", 1)[0].strip().decode("cp1252", errors="replace")

    return {
        "album": sid_text(header[22:54]),
        "artist": sid_text(header[54:86]),
        "copyright": sid_text(header[86:118]),
        "subsongs": unpack_from(">H", header, 14)[0],
    }


def nsfe_tags(stream, size):
    if stream.read(4) != b"NSFE":
        return {}
    while stream.tell() + 8 <= size:
        header = stream.read(8)
        if len(header) != 8:
            break
        length, kind = unpack_from("<I4s", header)
        if kind == b"NEND" or length > size - stream.tell():
            break
        if kind != b"auth":
            stream.seek(length, 1)
            continue
        if length > MAX_COMPOSER_TAG_BYTES:
            break
        tag = stream.read(length)
        fields = tag.split(b"\0", 2)
        if len(tag) == length and len(fields) >= 2 and (artist := tag_text(fields[1])):
            return {"artist": artist}
        break
    return {}


def gd3_tags(stream, size):
    header = stream.read(0x18)
    if len(header) != 0x18 or header[:4] != b"Vgm ":
        return {}
    offset = unpack_from("<I", header, 0x14)[0] + 0x14
    if not 0x18 <= offset <= size - 12:
        return {}
    stream.seek(offset)
    tag = stream.read(12)
    if len(tag) != 12 or tag[:4] != b"Gd3 ":
        return {}
    version, length = unpack_from("<II", tag, 4)
    if version != 0x100 or length % 2 or length > min(MAX_COMPOSER_TAG_BYTES, size - offset - 12):
        return {}
    content = stream.read(length)
    if len(content) != length:
        return {}
    # GD3 stores English and Japanese pairs for track, game, system and author.
    fields = content.decode("utf-16-le", errors="replace").split("\0", 8)
    if len(fields) < 8:
        return {}
    artist = fields[6].strip() or fields[7].strip()
    return {"artist": artist} if artist else {}


def vgm_tags(stream, size):
    compressed = stream.read(2) == b"\x1f\x8b"
    stream.seek(0)
    if not compressed:
        return gd3_tags(stream, size)
    try:
        with GzipFile(fileobj=stream, mode="rb") as decoded:
            return gd3_tags(decoded, MAX_VGZ_TAG_SCAN)
    except (OSError, EOFError, ZlibError):
        return {}


def read_tags(root, asset):
    if asset["format"] not in TRACK_TAG_FORMATS:
        return {}
    try:
        with open_vgm_location(root, asset) as stream:
            return stream_tags(stream, asset)
    except (OSError, ValueError, BadZipFile, NotImplementedError, EOFError):
        return {}


def add_track_tags(root, assets, formats):
    packed = defaultdict(list)
    for asset in assets:
        if asset["format"] not in formats:
            continue
        if asset.get("archive_format"):
            packed[asset["source_path"]].append(asset)
        else:
            asset.update(read_tags(root, asset))
    for locations in packed.values():
        try:
            with closing(packed_locations(root, locations)) as members:
                for asset, stream in members:
                    asset.update(stream_tags(stream, asset))
        except (OSError, ValueError, NotImplementedError, EOFError):
            # An unavailable member should not prevent importing the other sets.
            continue


def stream_tags(stream, asset):
    format_name = asset["format"]
    if format_name == "nsfe":
        return nsfe_tags(stream, asset["size_bytes"])
    if format_name in {"vgm", "vgz"}:
        return vgm_tags(stream, asset["size_bytes"])
    version = PSF_VERSIONS.get(format_name) or RELATED_PSF_VERSIONS.get(format_name)
    if version is not None:
        return psf_tags(stream, version, asset["size_bytes"])
    header = stream.read(0x100)
    if format_name == "sid":
        return sid_tags(header)
    if format_name == "nsf" and len(header) >= 0x80 and header[:5] == b"NESM\x1a":
        return {"album": tag_text(header[14:46]), "artist": tag_text(header[46:78]),
                "subsongs": header[6]}
    if format_name == "gbs" and len(header) >= 0x70 and header[:4] == b"GBS\x01":
        return {
            "album": tag_text(header[16:48]),
            "artist": tag_text(header[48:80]),
            "copyright": tag_text(header[80:112]),
            "subsongs": header[4],
        }
    if (format_name == "spc" and len(header) == 0x100
            and header.startswith(b"SNES-SPC700 Sound File Data") and header[35] == 0x1a):
        # The binary layout starts the author one byte earlier than the text layout.
        artist_start = 177 if header[176] < 32 or 48 <= header[176] <= 57 else 176
        return {"title": tag_text(header[46:78]), "album": tag_text(header[78:110]),
                "artist": tag_text(header[artist_start:208])}
    return {}
