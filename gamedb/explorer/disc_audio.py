"""Play the audio tracks declared by a verified Redump CUE sheet."""

from collections import defaultdict
from functools import lru_cache
from hashlib import sha1, sha256
import os
from pathlib import PurePosixPath
import re
import subprocess
from tempfile import NamedTemporaryFile
from threading import BoundedSemaphore, Lock
from zipfile import BadZipFile, ZipFile

from gamedb.catalog.disc_catalog import DISC_ADDON_PARENTS, DISC_SYSTEMS
from gamedb.explorer.related_media import _serve_file


CD_SECTOR_BYTES = 2352
FRAMES_PER_SECOND = 75
MAX_CUE_BYTES = 256 * 1024
CD_HARDWARE = {*DISC_ADDON_PARENTS, "32x-cd"}
DISC_AUDIO_PATH = re.compile(
    r"/related-media/disc-audio/(megadrive|pcengine|neogeo)/([0-9a-f]{32})/([0-9a-f]{32})/([0-9]{2})"
)
_conversions = BoundedSemaphore(2)
_cache_locks = [Lock() for _ in range(32)]


def cue_audio_tracks(content, files):
    """Resolve split tracks to exact archive members and skip their pregaps."""
    by_name = defaultdict(list)
    for member in files:
        by_name[PurePosixPath(member["memberPath"]).name].append(member)
    file_tracks = defaultdict(list)
    path = None
    for line in content.decode("utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if line.upper().startswith("FILE "):
            match = re.fullmatch(r'FILE\s+"([^"]+)"\s+BINARY', line, re.I)
            path = match[1] if match else None
        elif path and (match := re.fullmatch(r"TRACK\s+([0-9]{2})\s+(\S+)", line, re.I)):
            file_tracks[path].append([match[1], match[2].upper(), None])
        elif path and file_tracks[path] and (match := re.fullmatch(r"INDEX\s+01\s+(\d+):(\d{2}):(\d{2})", line, re.I)):
            minute, second, frame = map(int, match.groups())
            if second < 60 and frame < FRAMES_PER_SECOND:
                file_tracks[path][-1][2] = ((minute * 60 + second) * FRAMES_PER_SECOND + frame) * CD_SECTOR_BYTES

    tracks = {}
    for path, entries in file_tracks.items():
        members = by_name[path]
        if len(entries) != 1 or len(members) != 1:
            continue
        (number, kind, start), = entries
        member, = members
        if (kind == "AUDIO" and start is not None and number != "00"
                and start < member["size"] and not member["size"] % CD_SECTOR_BYTES
                and re.fullmatch(r"[0-9a-f]{40}", member["sha1"])):
            tracks[number] = (member["memberPath"], member["size"], member["sha1"], start)
    return tracks


@lru_cache(maxsize=256)
def _archive_tracks(path, _size, _mtime_ns, files):
    records = [dict(memberPath=name, size=length, sha1=digest) for name, length, digest in files]
    cues = [member for member in records if member["memberPath"].casefold().endswith(".cue")]
    if len(cues) != 1 or not 0 < cues[0]["size"] <= MAX_CUE_BYTES:
        return {}
    cue = cues[0]
    with ZipFile(path) as archive:
        info = archive.getinfo(cue["memberPath"])
        if cue["size"] != info.file_size:
            raise ValueError("The disc CUE sheet changed")
        content = archive.read(info)
    if sha1(content).hexdigest() != cue["sha1"]:
        raise ValueError("The disc CUE sheet changed")
    return cue_audio_tracks(content, records)


def _package_tracks(package):
    path = package["_path"]
    if package["sourceCollection"] != "Redump" or path.suffix.casefold() != ".zip":
        return {}
    files = tuple((item["memberPath"], item["size"], item["sha1"]) for item in package["files"])
    stat = path.stat()
    return _archive_tracks(path, stat.st_size, stat.st_mtime_ns, files)


def _disc_manifest(handler, platform, signature):
    manifest = handler._load_install_manifest(signature)
    if manifest is None:
        return None
    system = manifest["system"]
    valid = {DISC_SYSTEMS[addon] for addon, parent in DISC_ADDON_PARENTS.items() if parent == platform}
    return manifest if (system["manufacturer"], system["name"]) in valid else None


def disc_soundtracks(handler, platform, game):
    albums = {}
    for release in game["releases"]:
        if release.get("hardware") not in CD_HARDWARE or release["status"] != "matched":
            continue
        for archive in release.get("archives", ()):
            if not archive.get("installManifestUrl"):
                continue
            signature = archive["signature"]
            if signature not in albums:
                tracks = []
                try:
                    manifest = _disc_manifest(handler, platform, signature)
                    for package in manifest["packages"] if manifest else ():
                        prefix = "" if len(manifest["packages"]) == 1 else f"Disc {package['mediaSequence']} · "
                        package_key = package["packageSignature"]
                        base = f"/related-media/disc-audio/{platform}/{signature}/{package_key}"
                        for number in sorted(_package_tracks(package)):
                            title = f"{prefix}Track {number}"
                            tracks.append({"name": f"{title}.flac", "title": title, "format": "flac",
                                           "kind": "track", "playable": True, "url": f"{base}/{number}"})
                except (OSError, ValueError, BadZipFile, KeyError, RuntimeError, NotImplementedError):
                    tracks = []
                albums[signature] = {
                    "key": sha256(f"disc audio:{signature}".encode()).hexdigest(), "title": game["title"],
                    "collection": "Disc audio", "releases": [], "titleMatches": [], "assets": tracks,
                }
            if (album := albums[signature])["assets"]:
                album["releases"].append(release["key"])
                album["titleMatches"].append(release["key"])
                break
    return [album for album in albums.values() if album["assets"]]


def _playback_copy(cache, path, track):
    name, size, expected, start = track
    directory = cache / "disc-audio" / expected[:2]
    target = directory / f"{expected}-{start}.flac"
    with _cache_locks[int(expected[:2], 16) % len(_cache_locks)]:
        if target.is_file():
            return target
        directory.mkdir(parents=True, exist_ok=True)
        with _conversions, NamedTemporaryFile(dir=directory) as raw, NamedTemporaryFile(dir=directory) as output:
            digest = sha1()
            with ZipFile(path) as archive:
                info = archive.getinfo(name)
                if size != info.file_size:
                    raise ValueError("The disc audio track changed")
                with archive.open(info) as track_file:
                    while chunk := track_file.read(1024 * 1024):
                        digest.update(chunk)
                        raw.write(chunk)
            if raw.tell() != size or digest.hexdigest() != expected:
                raise ValueError("The disc audio track changed")
            raw.flush()
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-threads", "1", "-protocol_whitelist", "file",
                "-f", "s16le", "-ar", "44100", "-ac", "2", "-skip_initial_bytes", str(start), "-i", raw.name,
                "-map", "0:a:0", "-map_metadata", "-1", "-c:a", "flac", "-compression_level", "2",
                "-threads", "1", "-f", "flac", output.name,
            ], check=True, capture_output=True, timeout=60)
            try:
                os.link(output.name, target)
            except FileExistsError:
                pass
    return target


def serve_disc_audio(handler, platform, signature, package_key, number):
    if not handler.server.repository.retail_has_archive(platform, signature):
        return handler.send_error(404)
    try:
        manifest = _disc_manifest(handler, platform, signature)
        package = next((item for item in manifest["packages"] if item["packageSignature"] == package_key), None) if manifest else None
        track = _package_tracks(package).get(number) if package else None
        if not track:
            return handler.send_error(404)
        target = _playback_copy(handler.server.preview_cache.root, package["_path"], track)
        size = target.stat().st_size
    except (OSError, ValueError, BadZipFile, KeyError, RuntimeError, NotImplementedError, subprocess.SubprocessError):
        return handler.send_error(404, "Disc audio is unavailable")
    key = target.stem
    return _serve_file(handler, key, target.parent, {
        "path": f"Track {number}.flac", "revision": key,
        "locations": [{"size_bytes": size, "member_no": 0}],
    }, open_media=lambda *_: target.open("rb"), cache_control="private, max-age=86400")
