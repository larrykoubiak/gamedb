"""Group music files using the conventions of the source collections."""

import os
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from zipfile import BadZipFile, ZipFile

from libarchive.exception import ArchiveError

from gamedb.launchbox.matching import literal_title_key

from .amiga import AMIGA, AMIGA_CD32, AMIGA_CDTV, apply_game_notes, archived_game_alias, module_format
from .archives import members as archive_members, safe_member
from .joshw import COLLECTION as JOSHW_COLLECTION, PSF_COLLECTION, platform as joshw_platform, soundtrack_name

NES = ("Nintendo", "Nintendo Entertainment System")
GB = ("Nintendo", "Game Boy")
GBC = ("Nintendo", "Game Boy Color")
SNES = ("Nintendo", "Super Nintendo Entertainment System")
GENESIS = ("Sega", "Mega Drive")
MASTER_SYSTEM = ("Sega", "Master System")
SMS_POWER_COLLECTION = "SMS Power VGM"
CPC = ("Amstrad", "CPC")
C64 = ("Commodore", "C64")
ST = ("Atari", "ST")
PLAYSTATION = ("Sony", "PlayStation")
PS2 = ("Sony", "PlayStation 2")
NEOGEO = ("SNK", "Neo-Geo")
NEOGEO_COLLECTION = "VGMRips Neo Geo"
EARLY_CONSOLE_COLLECTIONS = {
    "VGMRips Atari 5200": ("Atari", "5200"),
    "VGMRips Atari 7800": ("Atari", "7800"),
    "VGMRips Intellivision": ("Mattel", "Intellivision"),
}

# A title at the root of one of these collections names a game set. Alphabet,
# composer and disc directories in the other collections have different roles.
SET_FOLDERS = {
    "spcsets": SNES,
    "spcsets_tmp": SNES,
    "snsf": SNES,
    "Genesis": GENESIS,
    "Project2612": GENESIS,
    "GC": ("Nintendo", "GameCube"),
    "PSF2": PS2,
    PSF_COLLECTION: PLAYSTATION,
    "The GameBoy Music Collection": GB,
    "Sega Game Gear": ("Sega", "Game Gear"),
    "PC-FX Disc Audio": ("NEC", "PC-FX"),
    "Planet Virtual Boy": ("Nintendo", "Virtual Boy"),
    NEOGEO_COLLECTION: NEOGEO,
    SMS_POWER_COLLECTION: MASTER_SYSTEM,
    **EARLY_CONSOLE_COLLECTIONS,
}
ARCHIVES = {".zip", ".rar", ".7z", ".rsn", ".vgm7z", ".lha", ".iso", ".d64", ".d71", ".d81", ".dfi"}
BROWSER_AUDIO = {".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac"}
DEPENDENCIES = {".psflib", ".psf2lib", ".snsflib", ".m3u", ".m3u8", ".cue", ".wd", ".wi", ".sep", ".seb"}
HANDHELD_STREAMS = {".at9", ".bcstm", ".bcwav", ".bfstm", ".bfwav", ".xvag"}
JOSHW_TRACKS = {
    ".2sf", ".adp", ".ads", ".adx", ".afc", ".aix", ".at3", ".gsf", ".gym", ".hes", ".hwas",
    ".kss", ".mgb", ".mini2sf", ".minigsf",
    ".minincsf", ".minissf", ".miniusf", ".ncsf", ".ssf", ".strm", ".swav", ".usf", ".wsr",
    ".dsf", ".minidsf", ".hps", ".dsp", ".ast", ".brstm", ".ss2", ".vag", ".vgmstream",
} | HANDHELD_STREAMS
JOSHW_LIBRARIES = {".2sflib", ".gsflib", ".ncsflib", ".ssflib", ".usflib", ".dsflib"}
NATIVE_AUDIO = {
    ".nsf", ".nsfe", ".sid", ".gbs", ".ay", ".ym", ".snd", ".sndh", ".sc68", ".vgm", ".vgz",
    ".spc", ".sgc", ".psf", ".minipsf", ".psf2", ".minipsf2", ".snsf", ".minisnsf", ".vsv",
    ".mib", ".ss2", ".genh", ".xa", ".str", ".bgm", ".mod", ".xm", ".stx", ".sa", ".mid",
    ".mmf", ".ape", ".aif", ".aiff", ".aifc", ".it", ".s3m", ".med", ".okt",
}
SUFFIXES = ARCHIVES | BROWSER_AUDIO | NATIVE_AUDIO | DEPENDENCIES
NOTES_COLLECTIONS = frozenset({
    "spcsets", "spcsets_tmp", PSF_COLLECTION, "UnExotica", "Genesis",
})
DATE_SUFFIX = re.compile(r"\s+\((?:19|20)[0-9x]{2}(?:-\d{2}){0,2}\).*$", re.IGNORECASE)
SPC_CODE = re.compile(r"\s+\[([a-z0-9_]+)\]$", re.IGNORECASE)
JOSH_TAG = re.compile(r"\s+\[([^\[\]]+)\]$")


@dataclass
class Soundtrack:
    key: str
    collection: str
    source_name: str
    title: str
    system: tuple[str, str] | None
    aliases: tuple[str, ...] = ()
    review_only: bool = False
    assets: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    match_basis: str = "source_title"
    source_evidence: dict = field(default_factory=dict)


def key_for(*parts: str) -> str:
    return sha256("\0".join(parts).encode()).hexdigest()


def identify(path: Path):
    """Return the source identity and scope supported by its path."""
    parts = path.parts
    collection = parts[0] if len(parts) > 1 else ""
    platform, review = None, False
    label = path.stem
    group = str(path.with_suffix(""))
    if collection in SET_FOLDERS:
        if len(parts) > 2:
            label = parts[1]
        if collection == "Sega Game Gear":
            # The named Zophar pack supplies game evidence. Playlist names and
            # the loose cartridge rip share a folder with no title in its name.
            if path.suffix.lower() != ".zip":
                return collection, collection, None, True
            label = label.removesuffix(".zophar").removesuffix(" (EMU)")
        platform = SET_FOLDERS[collection]
        if collection == SMS_POWER_COLLECTION and label.endswith("-SG"):
            platform = "Sega", "SG-1000"
        group = label
        if collection == "spcsets_tmp":
            collection = "spcsets"
    elif collection == JOSHW_COLLECTION and len(parts) > 2:
        platform = joshw_platform(parts[1], PurePosixPath(*parts[2:]))
        group = PurePosixPath(*parts[1:]).with_suffix("").as_posix()
        review = ("zzz_homebrew" in parts or "(Cover)" in path.stem
                  or (platform == ("Various", "Arcade")))
    elif collection in {"GBS", "Akumu_nsf_archive"}:
        platform = NES if collection == "Akumu_nsf_archive" else GB
        if collection == "GBS":
            if path.suffix.lower() not in ARCHIVES:
                review = True
            tag = re.search(r"\[(GBC|GB)\]$", label)
            if tag and tag[1] == "GBC":
                platform = GBC
    elif collection in {"ProjectAY", "UnExotica", "C64Music"}:
        if collection == "ProjectAY" and len(parts) > 3:
            platform = {"CPC": CPC, "Spectrum": ("Sinclair", "ZX Spectrum")}.get(parts[1])
            if parts[2].casefold() != "games":
                platform = None
        elif (collection == "C64Music" and parts[1] in {"GAMES", "MUSICIANS"}
              and path.suffix.lower() == ".sid"):
            platform, review = C64, True
        elif collection == "UnExotica" and parts[1] == "Game":
            # The notes provide the title and exact machine after grouping.
            platform, review = AMIGA, True
    elif collection in {"CPC-ym", "ST-ym", "sndh_lf", "sndh_sf"}:
        platform = CPC if collection == "CPC-ym" else ST
        game_scope = len(parts) == 3 or (len(parts) > 3 and parts[2].casefold() == "games")
        review = collection != "sndh_lf" or not game_scope or path.suffix.lower() != ".sndh"
    elif collection in {"MP3", "flac", "Midis", "sc68files_20031118"} and len(parts) > 2:
        label = group = parts[1]
    return collection, group, platform, review


def describe(path: Path, collection: str, group: str):
    if collection == JOSHW_COLLECTION:
        return soundtrack_name(path.parts[1], path) if len(path.parts) > 2 else (path.stem, ())
    label = group if collection in SET_FOLDERS or group in path.parts else path.stem
    if collection == NEOGEO_COLLECTION:
        return label.partition(" - ")[2] or label, ()
    if collection == "spcsets":
        # The long archive/directory name is the evidence. The bracketed code
        # identifies the rip, and track names and ID666 tags identify its audio.
        return SPC_CODE.sub("", label), ()
    psf_package = collection == PSF_COLLECTION and label.endswith("[PS1]") and DATE_SUFFIX.search(label)
    if collection in {"snsf", "C64Music"} or (collection == PSF_COLLECTION and not psf_package):
        return label.replace("_", " ").strip(), ()
    if collection == "Project2612":
        alternate = re.fullmatch(r"(.+) \(([^()]+)\)", label)
        if alternate:
            return alternate[1], (alternate[2],)
    label = DATE_SUFFIX.sub("", label)
    if collection in {"GBS", "Genesis", "PSF2"} or psf_package:
        label = re.sub(r"\s+\[(GB|GBC|PS1|PS2)\]$", "", label)
        alias = JOSH_TAG.search(label)
        if alias:
            return label[:alias.start()], (alias[1],)
    return label.replace("_", " ").strip(), ()


def asset_for(path: str, stat, *, member_no=0, member_name=None, size=None, crc=None):
    name = PurePosixPath(member_name or path).name
    suffix = Path(name).suffix.strip().lower()
    if suffix in ARCHIVES:
        kind = "archive"
    elif suffix in DEPENDENCIES | JOSHW_LIBRARIES or suffix == ".txt":
        kind = "support"
    else:
        kind = "track"
    return {
        "key": key_for(path, str(member_no), member_name or ""),
        "name": name,
        "format": suffix.lstrip("."),
        "kind": kind,
        "playable": suffix in BROWSER_AUDIO,
        "source_path": path,
        "size_bytes": stat.st_size if size is None else size,
        "mtime_ns": stat.st_mtime_ns,
        "member_no": member_no,
        "member_name": member_name,
        "crc32": crc,
    }


def zip_tracks(root: Path, asset: dict, *, formats=SUFFIXES - ARCHIVES):
    path = asset["source_path"]
    stat = (root / path).stat()
    with ZipFile(root / path) as archive:
        for number, member in enumerate(archive.infolist(), 1):
            name = PurePosixPath(member.filename)
            if member.is_dir() or member.flag_bits & 1 or not safe_member(member.filename):
                continue
            if name.suffix.lower() in formats or name.name.lower() == "info.txt":
                yield asset_for(path, stat, member_no=number, member_name=member.filename,
                                size=member.file_size, crc=f"{member.CRC:08x}")


def packed_tracks(root, asset, *, amiga=False, formats=None):
    path = asset["source_path"]
    archive = root / path
    stat = archive.stat()
    for number, name, size in archive_members(archive, asset["format"]):
        suffix = PurePosixPath(name).suffix.strip().lower()
        if formats is not None and suffix not in formats:
            continue
        track = asset_for(path, stat, member_no=number, member_name=name, size=size)
        if amiga:
            prefix, sample = module_format(name)
            if prefix:
                track.update(format=prefix, kind="support" if sample else "track", playable=False)
            elif suffix not in BROWSER_AUDIO | NATIVE_AUDIO:
                track.update(kind="support", playable=False)
        track.update(archive_format=asset["format"], archive_size_bytes=stat.st_size)
        yield track


def tracks_for_set(root, album):
    assets = album.assets
    if album.collection != JOSHW_COLLECTION and any(asset["kind"] == "track" for asset in assets):
        return
    formats = SUFFIXES - ARCHIVES
    if album.collection == JOSHW_COLLECTION:
        formats = formats | JOSHW_TRACKS | JOSHW_LIBRARIES | {".txt"}
        if album.system == ("Philips", "CD-i"):
            formats |= {".grn", ".mpg", ".txtp"}
    elif album.collection == PSF_COLLECTION:
        formats = formats | {".txt"}
    elif album.collection in {NEOGEO_COLLECTION, SMS_POWER_COLLECTION}:
        formats = {".vgm", ".vgz", ".txt"}
    for asset in assets[:]:
        try:
            if asset["format"] == "zip":
                tracks = list(zip_tracks(root, asset, formats=formats))
            elif asset["format"] == "lha" and album.collection == "UnExotica" and album.system == AMIGA:
                tracks = list(packed_tracks(root, asset, amiga=True))
            elif asset["format"] == "7z" and album.collection == "GBS":
                tracks = list(packed_tracks(root, asset, formats={".gbs", ".m3u", ".txt"}))
            elif asset["format"] == "7z" and album.collection in {JOSHW_COLLECTION, PSF_COLLECTION, NEOGEO_COLLECTION}:
                amiga = album.system in {AMIGA, AMIGA_CD32, AMIGA_CDTV}
                tracks = list(packed_tracks(root, asset, amiga=amiga, formats=None if amiga else formats))
            else:
                continue
        except (BadZipFile, ArchiveError):
            album.issues.append(f"Invalid {asset['format'].upper()}: {asset['source_path']}")
            continue
        assets.extend(tracks)
        if any(track["kind"] == "track" for track in tracks):
            break


def scan(root: Path, *, subdirectory: Path | None = None, source_paths: set[str] | None = None) -> list[Soundtrack]:
    source = root / subdirectory if subdirectory else root
    if not source.is_dir():
        raise FileNotFoundError(f"VGM source is unavailable: {source}")

    def fail(error):
        raise error

    sets = {}
    for directory, directories, files in os.walk(source, onerror=fail):
        directories[:] = sorted(n for n in directories if not n.startswith((".", "@")))
        for name in sorted(files):
            path = Path(directory, name)
            relative = path.relative_to(root)
            if source_paths is not None and relative.as_posix() not in source_paths:
                continue
            suffix = path.suffix.lower()
            is_note = suffix == ".txt" and relative.parts[0] in NOTES_COLLECTIONS
            joshw = relative.parts[0] == JOSHW_COLLECTION
            if name.startswith(".") or (name.startswith("@") and not joshw):
                continue
            if suffix not in SUFFIXES and not is_note and not (joshw and suffix in JOSHW_TRACKS):
                continue
            stat = path.lstat()
            if not S_ISREG(stat.st_mode):
                continue
            collection, group, system, review = identify(relative)
            if joshw and not system:
                continue
            key = key_for(collection, group if joshw else literal_title_key(group), *(system or ()))
            if key not in sets:
                title, aliases = describe(relative, collection, group)
                sets[key] = Soundtrack(key, collection or "By Format", group, title, system, aliases, review)
                if joshw:
                    sets[key].match_basis = "joshw_filename"
            sets[key].assets.append(asset_for(relative.as_posix(), stat))
    for key, soundtrack in list(sets.items()):
        if soundtrack.collection != "By Format":
            continue
        group = literal_title_key(soundtrack.source_name)
        spc_set = sets.get(key_for("spcsets", group, *SNES))
        if not spc_set or len(soundtrack.assets) != 1:
            continue
        archive = soundtrack.assets[0]
        if archive["format"] != "zip":
            continue
        try:
            tracks = [asset for asset in zip_tracks(root, archive) if asset["kind"] == "track"]
        except BadZipFile:
            continue  # The normal ZIP scan records the issue below.
        if tracks and all(asset["format"] == "spc" for asset in tracks):
            spc_set.assets.append(archive)
            del sets[key]
    for soundtrack in sets.values():
        tracks_for_set(root, soundtrack)
        assets = soundtrack.assets
        if soundtrack.collection == JOSHW_COLLECTION:
            package = next((asset for asset in assets if asset["kind"] == "archive"), assets[0])
            soundtrack.source_evidence = {"joshwPath": package["source_path"].partition("/")[2]}
            if soundtrack.system in {AMIGA_CD32, AMIGA_CDTV} and (alias := archived_game_alias(root, soundtrack)):
                title, entry = alias
                soundtrack.aliases = tuple(dict.fromkeys((*soundtrack.aliases, title)))
                soundtrack.source_evidence.update(joshwDiscTitle=title, joshwDiscNotes=entry)
        if (soundtrack.collection == "UnExotica" and soundtrack.system == AMIGA
                and any(asset.get("archive_format") == "lha" for asset in assets)):
            apply_game_notes(root, soundtrack)
        if soundtrack.collection == "sndh_lf" and not soundtrack.review_only:
            soundtrack.match_basis = "sndh_long_filename"
        if soundtrack.collection == "flac" and not any(asset["kind"] == "track" for asset in assets):
            soundtrack.issues.append("Album has cue sheets but no audio files")
        assets.sort(key=lambda asset: (asset["kind"], asset["source_path"].casefold(),
                                      (asset["member_name"] or "").casefold()))
    return sorted(
        (soundtrack for soundtrack in sets.values()
         if soundtrack.issues or any(asset["kind"] != "support" for asset in soundtrack.assets)),
        key=lambda item: (item.collection.casefold(), item.source_name.casefold(), item.key),
    )
