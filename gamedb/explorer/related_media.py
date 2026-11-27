"""Serve source-owned catalog attachments and their artwork previews."""

from base64 import b64encode
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from functools import lru_cache
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from stat import S_ISREG
from urllib.parse import quote, urlsplit
from zipfile import BadZipFile, ZipFile

from gamedb.catalog.manuals import manual_key
from gamedb.catalog.patching import N64_DISK_LAYOUT, apply_translation, rom_size_limit, supports_patching
from gamedb.catalog.translations import (
    ADDON_CONSOLES, ADDON_EXTENSIONS, CARTRIDGE_EXTENSIONS, DISC_LAYOUT, DISC_PATCH_ARCHIVES, DISC_PLATFORMS, FORMATS,
    INDEX_NAME as TRANSLATION_INDEX, INDEX_VERSION, MAX_PATCH_SIZE, TRANSLATION_ROOTS, translation_order,
)
from gamedb.exo.media import location_path, open_location
from gamedb.explorer.manuals import manual_location
from gamedb.explorer.soundtrack_audio import browser_flac
from gamedb.vgm.archives import open_vgm_location


def serve(handler, key, *, revision=None, preview_size=None):
    asset = handler.server.repository.exo_asset(key)
    if (
        not asset
        or revision
        and (asset["revision"] != revision or asset["kind"] != "artwork")
    ):
        return handler.send_error(HTTPStatus.NOT_FOUND)
    if asset["kind"] == "url":
        target = asset["path"]
        if (
            urlsplit(target).scheme.lower() not in ("http", "https")
            or not urlsplit(target).netloc
            or any(ord(c) < 32 for c in target)
        ):
            return handler.send_error(HTTPStatus.NOT_FOUND)
        handler.send_response(HTTPStatus.FOUND)
        handler.send_header("Location", target)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    return _serve_file(handler, key, handler.server.exo_root, asset, revision, preview_size)


def serve_vgm(handler, key, *, flac=False):
    root = handler.server.vgm_root
    if root is None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    location = handler.server.repository.vgm_asset(key)
    if not location:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    return serve_vgm_file(handler, root, key, location, flac=flac)


def serve_vgm_file(handler, root, key, location, *, flac=False):
    if flac:
        try:
            track = browser_flac(handler.server.preview_cache.root, root, key, location)
            size = track.stat().st_size
        except (OSError, ValueError, subprocess.SubprocessError):
            return handler.send_error(HTTPStatus.NOT_FOUND, "Soundtrack playback copy unavailable")
        return _serve_file(handler, key, track.parent, {
            "path": str(Path(location["name"]).with_suffix(".flac")),
            "revision": location["mtime_ns"],
            "locations": [{"size_bytes": size, "member_no": 0}],
        }, open_media=lambda *_: track.open("rb"), content_type="audio/flac")
    return _serve_file(handler, key, root, {
        "path": location["name"],
        "revision": location["mtime_ns"],
        "locations": [location],
    }, force_download=not location["playable"], open_media=open_vgm_location)


def add_local_manuals(game, root, platform):
    for release in game["releases"]:
        for manual in release.get("manuals", ()):
            key = manual_key(manual["url"])
            if manual_location(root, key):
                manual.update(
                    localUrl=f"/related-media/{platform}-manual/{key}",
                    preview=f"/previews/320/{platform}-manual/{key}",
                    format="PDF",
                )


def serve_retail_manual(handler, root, key, *, preview_size=None):
    location = manual_location(root, key)
    if location is None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    return _serve_manual_file(handler, key, root, location, preview_size)


def serve_retail_manual_pages(handler, root, key, page=None):
    location = manual_location(root, key)
    if location is None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    cache = handler.server.preview_cache
    try:
        source = location_path(root, location["source_path"])
        pages = cache.manual_pages(source, (location["size_bytes"], location["mtime_ns"]))
    except (OSError, ValueError):
        return handler.send_error(HTTPStatus.NOT_FOUND, "Manual pages unavailable")
    if page is None:
        return handler._json_response({"pages": pages})
    if not 1 <= page <= len(pages):
        return handler.send_error(HTTPStatus.NOT_FOUND)
    return _serve_manual_file(handler, key, root, location, cache.MANUAL_PAGE_SIZE, page)


def _serve_manual_file(handler, key, root, location, preview_size, page=1):
    return _serve_file(handler, key, root, {
        "path": Path(location["source_path"]).with_suffix(".webp") if preview_size else location["source_path"],
        "revision": location["mtime_ns"],
        "locations": [location],
    }, revision=location["mtime_ns"], preview_size=preview_size, preview_page=page)


@lru_cache(maxsize=len(TRANSLATION_ROOTS))
def _read_translation_index(path, revision):
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != INDEX_VERSION:
        return {}, {}
    records = {}
    by_signature = defaultdict(list)
    for record in document["translations"]:
        key = record["key"]
        disc = record["layout"] == DISC_LAYOUT
        cartridge_formats = FORMATS | {"xdelta"} if supports_patching("xdelta", record["layout"]) else FORMATS
        valid_patch = (record["format"] in DISC_PATCH_ARCHIVES and record["size"] > 0) if disc else (
            record["format"] in cartridge_formats and 0 < record["size"] <= MAX_PATCH_SIZE
        )
        if record["layout"] == N64_DISK_LAYOUT:
            valid_patch = (record["format"] == "ppf" and 0 < record["size"] <= MAX_PATCH_SIZE
                           and re.fullmatch(r"[0-9a-f]{40}", record.get("outputSha1", "")))
        if (not re.fullmatch(r"[0-9a-f]{64}", key) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                or not valid_patch):
            continue
        records[key] = record
        for signature in record["signatures"]:
            by_signature[signature].append(record)
    return records, by_signature


def translation_index_revision(root):
    if root is None:
        return None
    try:
        stat = (root / TRANSLATION_INDEX).stat()
    except OSError:
        return None
    return stat.st_ino, stat.st_mtime_ns, stat.st_size


def _translation_index(root):
    revision = translation_index_revision(root)
    if revision is None:
        return {}, {}
    try:
        return _read_translation_index(root / TRANSLATION_INDEX, revision)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return {}, {}


def _translation_location(root, record):
    relative = f"patches/{record['sha256']}.{record['format']}"
    try:
        stat = location_path(root, relative).stat()
        if not S_ISREG(stat.st_mode) or stat.st_size != record["size"]:
            return None
    except (OSError, ValueError):
        return None
    return {"source_path": relative, "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "member_no": 0, "sha256": record["sha256"]}


def _disc_set_location(root, record):
    try:
        artifact = record["discSet"]
        digest = artifact["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        relative = f"discs/{digest}.zip"
        stat = location_path(root, relative).stat()
        if (not S_ISREG(stat.st_mode) or stat.st_size != artifact["size"]
                or stat.st_mtime_ns != artifact["mtimeNs"]):
            return None
    except (KeyError, OSError, TypeError, ValueError):
        return None
    return {"source_path": relative, "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "member_no": 0}


def _disc_launch_path(root, location):
    try:
        with ZipFile(location_path(root, location["source_path"])) as archive:
            names = [member.filename for member in archive.infolist() if not member.is_dir()]
    except (OSError, ValueError, BadZipFile):
        return None
    if "Play.m3u" in names:
        return "Play.m3u"
    for extensions in ((".cue", ".gdi"), (".iso", ".cdi", ".chd")):
        launch_files = [name for name in names if name.lower().endswith(extensions)]
        if len(launch_files) == 1:
            launch = launch_files[0]
            if Path(launch).name == launch and "\\" not in launch and launch.isprintable():
                return launch
    return None


def add_local_translations(game, root, platform="snes"):
    _, by_signature = _translation_index(root)
    for release in game["releases"]:
        if release["status"] != "matched":
            continue
        archives = release.get("archives", ())
        if platform == "neogeo":
            archives = [{"signature": arcade["installSignature"], "archiveNames": [f"{arcade['setName']}.zip"]}
                        for arcade in release.get("arcadeSets", ()) if arcade["complete"]]
        matches = {}
        for archive in archives:
            for record in by_signature.get(archive["signature"], ()):
                if record["key"] in matches or not _translation_location(root, record):
                    continue
                public = {field: value for field, value in record.items() if field not in {"signatures", "discSet", "mtimeNs"}}
                public["baseReleaseSignature"] = archive["signature"]
                public["url"] = f"/related-media/{platform}-translation/{record['key']}"
                if platform == "nes":
                    public["sourceUrl"] = f"https://neoromhacking.net/translationpage.php?id={record['rhdnId']}"
                disc = platform in DISC_PLATFORMS and record["layout"] == DISC_LAYOUT
                disc_location = _disc_set_location(root, record) if disc else None
                if disc_location:
                    public["discDownloadSize"] = disc_location["size_bytes"]
                    public["discDownloadSha256"] = record["discSet"]["sha256"]
                    if launch_path := _disc_launch_path(root, disc_location):
                        public["discLaunchPath"] = launch_path
                if disc_location or supports_patching(record["format"], record["layout"]):
                    public["romDownloadUrl"] = (
                        f"/api/v1/releases/{archive['signature']}/translations/{record['key']}/download"
                    )
                if len(archives) > 1:
                    public["baseArchive"] = archive["archiveNames"][0]
                matches[record["key"]] = public
        if matches:
            release["translations"] = [*sorted(matches.values(), key=translation_order), *release.get("translations", ())]


def add_translation_availability(games, root, extra_roots=()):
    available = set()
    for index in (root, *extra_roots):
        _, by_signature = _translation_index(index)
        available.update(signature for signature, records in by_signature.items()
                         if any(_translation_location(index, record) for record in records))
    for game in games:
        for release in game["releases"]:
            signatures = release.pop("archiveSignatures", ())
            release["hasTranslations"] = release["status"] == "matched" and (
                release.get("hasTranslations", False) or not available.isdisjoint(signatures)
            )


@contextmanager
def _open_translation(root, location):
    with open_location(root, location) as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != location["sha256"]:
            raise ValueError("Translation patch checksum changed")
        stream.seek(0)
        yield stream


def serve_retail_translation(handler, platform, key):
    root = handler.server.retail_translation_roots[platform]
    records, _ = _translation_index(root)
    record = records.get(key)
    location = _translation_location(root, record) if record else None
    if location is None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    return _serve_file(handler, key, root, {
        "path": record["filename"], "revision": record["sha256"], "locations": [location],
    }, force_download=True, open_media=_open_translation)


def serve_retail_translation_rom(handler, signature, key, *, disc_only=False):
    from gamedb.catalog.disc_catalog import DISC_ADDON_PARENTS
    from gamedb.explorer.server import _resolve_rom_path

    for platform, root in handler.server.retail_translation_roots.items():
        if disc_only and platform not in DISC_PLATFORMS:
            continue
        records, _ = _translation_index(root)
        record = records.get(key)
        if record and signature in record["signatures"]:
            break
    else:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    if platform in DISC_PLATFORMS and record["layout"] == DISC_LAYOUT:
        location = _disc_set_location(root, record)
        parent = DISC_ADDON_PARENTS.get(platform, platform)
        if location is None or not handler.server.repository.retail_has_archive(parent, signature):
            return handler._json_response({"error": "The verified disc set is unavailable."}, HTTPStatus.NOT_FOUND)
        digest = record["discSet"]["sha256"]
        return _serve_file(handler, key, root, {
            "path": record["discSet"]["filename"], "revision": digest, "locations": [location],
        }, force_download=True, cache_control="private, no-store", representation_sha256=digest)
    if disc_only:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    if not supports_patching(record["format"], record["layout"]):
        return handler._json_response({"error": "This patch requires a different ROM layout."}, HTTPStatus.CONFLICT)
    patch_location = _translation_location(root, record)
    if patch_location is None:
        return handler._json_response({"error": "The translation patch is unavailable."}, HTTPStatus.NOT_FOUND)

    rom = handler.server.repository.retail_translation_base(platform, signature, record["baseSha1"])
    if rom is None:
        return handler._json_response({"error": "The verified base ROM is unavailable."}, HTTPStatus.CONFLICT)
    rom_limit = rom_size_limit(record["layout"])
    try:
        path = _resolve_rom_path(handler.server.rom_root, rom["path"])
        with ZipFile(path) as archive, archive.open(rom["member_path"]) as member:
            original = member.read(rom_limit + 1)
    except (BadZipFile, KeyError, NotImplementedError, OSError, RuntimeError, ValueError):
        return handler._json_response({"error": "The verified base ROM is unavailable."}, HTTPStatus.CONFLICT)
    if len(original) > rom_limit or hashlib.sha1(original).hexdigest() != record["baseSha1"]:
        return handler._json_response({"error": "The base ROM checksum or size has changed."}, HTTPStatus.CONFLICT)

    try:
        with open_location(root, patch_location) as file:
            patch = file.read(record["size"] + 1)
    except (OSError, ValueError):
        return handler._json_response({"error": "The translation patch has changed."}, HTTPStatus.CONFLICT)
    if len(patch) != record["size"] or hashlib.sha256(patch).hexdigest() != record["sha256"]:
        return handler._json_response({"error": "The translation patch has changed."}, HTTPStatus.CONFLICT)
    try:
        header = record.get("outputHeader")
        patched = apply_translation(original, patch, record["format"], record["layout"],
                                    pad_to_size=record.get("padToSize"),
                                    output_header=bytes.fromhex(header) if header else None)
    except ValueError as error:
        return handler._json_response({"error": str(error)}, HTTPStatus.CONFLICT)
    if (expected_sha1 := record.get("outputSha1")) and hashlib.sha1(patched).hexdigest() != expected_sha1:
        return handler._json_response({"error": "The patched ROM checksum does not match."}, HTTPStatus.CONFLICT)

    base_name = Path(rom["member_path"].replace("\\", "/")).stem
    tag = " ".join(item for item in (record["language"], record["version"]) if item)
    addon_extension = ADDON_EXTENSIONS.get(ADDON_CONSOLES.get(platform))
    extension = addon_extension if addon_extension and record.get("extension") == addon_extension else CARTRIDGE_EXTENSIONS[platform]
    if record["layout"] == N64_DISK_LAYOUT:
        extension = "ndd"
    filename = re.sub(r"[/\\\x00-\x1f\x7f]", "_", f"{base_name} [{tag}].{extension}")
    digest = hashlib.sha256(patched).hexdigest()
    return _serve_file(handler, key, root, {
        "path": filename, "revision": digest,
        "locations": [{"size_bytes": len(patched), "member_no": 0}],
    }, force_download=True, open_media=lambda *_: BytesIO(patched), cache_control="private, no-store",
        representation_sha256=digest)


def _serve_file(handler, key, root, asset, revision=None, preview_size=None, *,
                force_download=False, open_media=open_location, preview_page=1, cache_control=None,
                representation_sha256=None, content_type=None):
    from gamedb.explorer.server import _byte_range

    name = Path(asset["path"]).name
    with ExitStack() as stack:
        for location in asset["locations"] or ():
            try:
                stream = stack.enter_context(open_media(root, location))
                break
            except (OSError, ValueError, BadZipFile, NotImplementedError):
                continue
        else:
            return handler.send_error(HTTPStatus.NOT_FOUND, "Archived item unavailable")
        size = location["size_bytes"]
        mime = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        if preview_size:
            cache = handler.server.preview_cache
            try:
                if location["member_no"]:
                    directory = cache.root / "exo" / revision
                    directory.mkdir(parents=True, exist_ok=True)
                    original = directory / key
                    if not original.is_file():
                        with tempfile.NamedTemporaryFile(
                            dir=directory, delete=False
                        ) as temp:
                            try:
                                shutil.copyfileobj(stream, temp)
                                temp.flush()
                                os.replace(temp.name, original)
                            finally:
                                Path(temp.name).unlink(missing_ok=True)
                else:
                    original = location_path(root, location["source_path"])
                path = cache.get(original, preview_size, page=preview_page)
                stream = stack.enter_context(path.open("rb"))
                size, mime = path.stat().st_size, "image/webp"
            except (OSError, ValueError, SyntaxError, BadZipFile):
                return handler.send_error(HTTPStatus.NOT_FOUND)
        page_tag = f"-page-{preview_page}" if preview_page != 1 else ""
        etag = f'"{asset["revision"]}-{key}-{preview_size or 0}-{location["member_no"]}{page_tag}"'
        if handler.headers.get("If-None-Match") == etag:
            handler.send_response(HTTPStatus.NOT_MODIFIED)
            handler.send_header("ETag", etag)
            if cache_control:
                handler.send_header("Cache-Control", cache_control)
            handler.end_headers()
            return
        try:
            requested = _byte_range(handler.headers.get("Range"), size)
        except ValueError:
            handler.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            handler.send_header("Content-Range", f"bytes */{size}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        start, end = requested or (0, size - 1)
        remaining = end - start + 1
        if start:
            stream.seek(start)
        handler.send_response(
            HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK
        )
        if requested:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(remaining))
        handler.send_header("Content-Type", mime)
        if representation_sha256:
            digest = b64encode(bytes.fromhex(representation_sha256)).decode("ascii")
            handler.send_header("Repr-Digest", f"sha-256=:{digest}:")
        # A source HTML supplement can be downloaded without running active
        # content under the Explorer origin.
        inline = not force_download and (
            mime in ("application/pdf", "text/plain")
            or mime.startswith(("video/", "audio/"))
            or mime
            in ("image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp")
        )
        disposition = "inline" if inline else "attachment"
        handler.send_header(
            "Content-Disposition",
            f"{disposition}; filename*=UTF-8''{quote(name, safe='')}",
        )
        handler.send_header("X-Content-Type-Options", "nosniff")
        if not inline:
            handler.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        handler.send_header(
            "Cache-Control", cache_control or ("public, max-age=3600" if revision else "public, no-cache")
        )
        handler.send_header("ETag", etag)
        handler.end_headers()
        if handler.command == "HEAD":
            return
        while remaining:
            data = stream.read(min(remaining, 1024 * 1024))
            if not data:
                break
            try:
                handler.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                return
            remaining -= len(data)
