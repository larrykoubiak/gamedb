"""Group music files using the conventions of the source collections."""

import os
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from zipfile import BadZipFile, ZipFile

from gamedb.launchbox.matching import literal_title_key

NES = ("Nintendo", "Nintendo Entertainment System")
GB = ("Nintendo", "Game Boy")
GBC = ("Nintendo", "Game Boy Color")
SNES = ("Nintendo", "Super Nintendo Entertainment System")
GENESIS = ("Sega", "Mega Drive")
CPC = ("Amstrad", "CPC")
C64 = ("Commodore", "C64")
ST = ("Atari", "ST")
AMIGA = ("Commodore", "Amiga")
PLAYSTATION = ("Sony", "PlayStation")
PS2 = ("Sony", "PlayStation 2")
PSF_COLLECTION = "The PlayStation Music Collection PSF"

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
}
ARCHIVES = {".zip", ".rar", ".7z", ".rsn", ".vgm7z", ".lha", ".iso", ".d64", ".d71", ".d81", ".dfi"}
BROWSER_AUDIO = {".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac"}
DEPENDENCIES = {".psflib", ".psf2lib", ".snsflib", ".m3u", ".m3u8", ".cue", ".wd", ".wi", ".sep", ".seb"}
NATIVE_AUDIO = {
    ".nsf", ".nsfe", ".sid", ".gbs", ".ay", ".ym", ".snd", ".sndh", ".sc68", ".vgm", ".vgz",
    ".spc", ".sgc", ".psf", ".minipsf", ".psf2", ".minipsf2", ".snsf", ".minisnsf", ".vsv",
    ".mib", ".ss2", ".genh", ".xa", ".str", ".bgm", ".mod", ".xm", ".stx", ".sa", ".mid",
    ".mmf", ".ape", ".it", ".s3m",
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
        group = label
        if collection == "spcsets_tmp":
            collection = "spcsets"
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
            # This archive also contains CD32/CDTV tracks. Keep it reviewable
            # until there is explicit platform evidence per set.
            platform, review = AMIGA, True
    elif collection in {"CPC-ym", "ST-ym", "sndh_lf", "sndh_sf"}:
        platform = CPC if collection == "CPC-ym" else ST
        review = True
    elif collection in {"MP3", "flac", "Midis", "sc68files_20031118"} and len(parts) > 2:
        label = group = parts[1]
    return collection, group, platform, review


def describe(path: Path, collection: str, group: str):
    label = group if collection in SET_FOLDERS or group in path.parts else path.stem
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
    suffix = Path(name).suffix.lower()
    kind = "archive" if suffix in ARCHIVES else "support" if suffix in DEPENDENCIES or suffix == ".txt" else "track"
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


def zip_tracks(root: Path, asset: dict):
    path = asset["source_path"]
    stat = (root / path).stat()
    with ZipFile(root / path) as archive:
        for number, member in enumerate(archive.infolist(), 1):
            name = PurePosixPath(member.filename)
            if (member.is_dir() or member.flag_bits & 1 or name.is_absolute()
                    or any(part == ".." or part.startswith((".", "@")) for part in name.parts)):
                continue
            if name.suffix.lower() in (SUFFIXES - ARCHIVES) or name.name.lower() == "info.txt":
                yield asset_for(path, stat, member_no=number, member_name=member.filename,
                                size=member.file_size, crc=f"{member.CRC:08x}")


def scan(root: Path) -> list[Soundtrack]:
    if not root.is_dir():
        raise FileNotFoundError(f"VGM source is unavailable: {root}")

    def fail(error):
        raise error

    sets = {}
    for directory, directories, files in os.walk(root, onerror=fail):
        directories[:] = sorted(n for n in directories if not n.startswith((".", "@")))
        for name in sorted(files):
            path = Path(directory, name)
            relative = path.relative_to(root)
            suffix = path.suffix.lower()
            is_note = suffix == ".txt" and relative.parts[0] in NOTES_COLLECTIONS
            if name.startswith((".", "@")) or not (suffix in SUFFIXES or is_note):
                continue
            stat = path.lstat()
            if not S_ISREG(stat.st_mode):
                continue
            collection, group, system, review = identify(relative)
            key = key_for(collection, literal_title_key(group), *(system or ()))
            if key not in sets:
                title, aliases = describe(relative, collection, group)
                sets[key] = Soundtrack(key, collection or "By Format", group, title, system, aliases, review)
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
        assets = soundtrack.assets
        if not any(asset["kind"] == "track" for asset in assets):
            # Prefer loose tracks when the same set also has an archive copy.
            # Otherwise the first readable ZIP supplies the track list.
            for asset in assets[:]:
                if asset["format"] != "zip":
                    continue
                try:
                    tracks = list(zip_tracks(root, asset))
                except BadZipFile:
                    soundtrack.issues.append(f"Invalid ZIP: {asset['source_path']}")
                    continue
                assets.extend(tracks)
                if any(track["kind"] == "track" for track in tracks):
                    break
        if soundtrack.collection == "flac" and not any(asset["kind"] == "track" for asset in assets):
            soundtrack.issues.append("Album has cue sheets but no audio files")
        assets.sort(key=lambda asset: (asset["kind"], asset["source_path"].casefold(),
                                      (asset["member_name"] or "").casefold()))
    return sorted(
        (soundtrack for soundtrack in sets.values()
         if soundtrack.issues or any(asset["kind"] != "support" for asset in soundtrack.assets)),
        key=lambda item: (item.collection.casefold(), item.source_name.casefold(), item.key),
    )
