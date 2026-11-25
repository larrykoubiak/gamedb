"""Read source labels without decoding chiptune audio."""

import re
from collections import defaultdict
from contextlib import closing
from gzip import GzipFile
from pathlib import PurePosixPath
from struct import unpack_from
from zipfile import BadZipFile
from zlib import error as ZlibError

from .archives import open_vgm_location, packed_locations

PSF_VERSIONS = {"psf": 1, "minipsf": 1, "psf2": 2, "minipsf2": 2}
RELATED_PSF_VERSIONS = {
    "ssf": 0x11, "minissf": 0x11,
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
MAX_NSF_TAG_BYTES = 64 * 1024
MAX_VGZ_TAG_SCAN = 64 * 1024**2
PLAYLIST_FORMATS = {"m3u", "m3u8"}
PLAYLIST_ENTRY = re.compile(rb"(.+)::(NSF|HES),\s*(\$[a-f0-9]{1,2}|[0-9]{1,3})\s*,\s*((?:\\.|[^,\\])*)", re.I)


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


def nsf_chunks(stream, size):
    chunks = {}
    while stream.tell() + 8 <= size:
        header = stream.read(8)
        if len(header) != 8:
            break
        length, kind = unpack_from("<I4s", header)
        if kind == b"NEND" or length > size - stream.tell():
            break
        if kind not in (b"INFO", b"auth", b"tlbl", b"plst") or length > MAX_NSF_TAG_BYTES:
            stream.seek(length, 1)
            continue
        data = stream.read(length)
        if len(data) != length:
            break
        chunks.setdefault(kind, data)
    return chunks


def nsf_subsong_tags(count, first_song, labels, playlist=b""):
    # The decoder addresses at most the number of tracks in the file header.
    order = playlist[:count] or range(count)
    tags = {"subsongs": len(order)}
    if count:
        tags["default_subsong"] = first_song if 1 <= first_song <= len(order) else 1
    if labels:
        names = [tag_text(raw) for raw in labels.split(b"\0", count)[:count]]
        titles = [names[index] if index < len(names) else "" for index in order]
        if any(titles):
            tags["subsong_titles"] = titles
    return tags


def nsfe_tags(stream, size):
    if stream.read(4) != b"NSFE":
        return {}
    chunks = nsf_chunks(stream, size)
    tags = {}
    fields = chunks.get(b"auth", b"").split(b"\0", 2)
    if len(fields) >= 2 and (artist := tag_text(fields[1])):
        tags["artist"] = artist
    info = chunks.get(b"INFO", b"")
    if len(info) >= 9 and info[8]:
        playlist = chunks.get(b"plst", b"")
        first_song = info[9] + 1 if len(info) >= 10 and not playlist else 1
        tags.update(nsf_subsong_tags(info[8], first_song, chunks.get(b"tlbl", b""), playlist))
    return tags


def nsf_tags(stream, header, size):
    labels = b""
    program_size = int.from_bytes(header[0x7d:0x80], "little")
    if program_size and 0x80 + program_size + 8 <= size:
        # Both version 1 and NSF2 can append optional NSFe chunks after the program.
        stream.seek(0x80 + program_size)
        labels = nsf_chunks(stream, size).get(b"tlbl", b"")
    return {"album": tag_text(header[14:46]), "artist": tag_text(header[46:78]),
            **nsf_subsong_tags(header[6], header[7], labels)}


def playlist_location(asset):
    if member := asset.get("member_name"):
        return asset["source_path"], PurePosixPath(member)
    return None, PurePosixPath(asset["source_path"])


def read_track_playlist(stream, asset, playlists, formats):
    archive, path = playlist_location(asset)
    for line in stream.read(MAX_NSF_TAG_BYTES).removeprefix(b"\xef\xbb\xbf").splitlines():
        line = line.strip()
        if line.startswith(b"#") or not (entry := PLAYLIST_ENTRY.match(line)):
            continue
        name, kind, number, label = entry.groups()
        format_name = kind.decode("ascii").lower()
        if format_name not in formats or (format_name == "nsf" and number.startswith(b"$")):
            continue
        index = int(number[1:], 16) if number.startswith(b"$") else int(number)
        if format_name == "hes":
            # M3U uses the HES driver ID. ZXTune addresses the same song from one.
            if index > 255:
                continue
            index += 1
        filename = tag_text(name).replace("\\,", ",").replace("\\", "/")
        if not filename.lower().endswith(f".{format_name}"):
            filename += f".{format_name}"
        title = tag_text(re.sub(rb"\\([,\\])", rb"\1", label))
        if title or format_name == "hes":
            songs = playlists[archive, path.parent / filename]
            if songs.setdefault(index, title) != title:
                songs[index] = ""


def add_playlist_tracks(assets, playlists):
    for asset in assets:
        format_name = asset["format"]
        if format_name not in {"nsf", "hes"} or not (songs := playlists.get(playlist_location(asset))):
            continue
        if format_name == "hes":
            asset["playlist_songs"] = [{"number": number, "title": title} for number, title in songs.items()]
            continue
        if not (count := asset.get("subsongs")):
            continue
        titles = list(asset.get("subsong_titles", ()))
        titles.extend([""] * (count - len(titles)))
        for index, title in songs.items():
            if title and 1 <= index <= count and not titles[index - 1]:
                titles[index - 1] = title
        if any(titles):
            asset["subsong_titles"] = titles


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
    playlists = defaultdict(dict)
    playlist_targets = {asset["format"] for asset in assets} & formats & {"nsf", "hes"}

    def enrich(asset, stream):
        if asset["format"] in PLAYLIST_FORMATS:
            read_track_playlist(stream, asset, playlists, playlist_targets)
        else:
            asset.update(stream_tags(stream, asset))

    for asset in assets:
        playlist = (playlist_targets and asset["format"] in PLAYLIST_FORMATS
                    and asset["size_bytes"] <= MAX_NSF_TAG_BYTES)
        if (asset["format"] not in formats or asset["format"] == "hes") and not playlist:
            continue
        if asset.get("archive_format"):
            packed[asset["source_path"]].append(asset)
        elif playlist:
            try:
                with open_vgm_location(root, asset) as stream:
                    enrich(asset, stream)
            except (OSError, ValueError, BadZipFile, NotImplementedError, EOFError):
                continue
        else:
            asset.update(read_tags(root, asset))
    for locations in packed.values():
        try:
            with closing(packed_locations(root, locations)) as members:
                for asset, stream in members:
                    enrich(asset, stream)
        except (OSError, ValueError, NotImplementedError, EOFError):
            # An unavailable member should not prevent importing the other sets.
            continue
    if playlists:
        add_playlist_tracks(assets, playlists)


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
        return nsf_tags(stream, header, asset["size_bytes"])
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
