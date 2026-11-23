"""Serve source-owned catalog attachments and their artwork previews."""

import hashlib
import json
import mimetypes
import re
import shutil
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
from gamedb.catalog.patching import MAX_ROM_SIZE, PatchError, apply_translation, supports_patching
from gamedb.catalog.translations import (
    FORMATS, INDEX_NAME as TRANSLATION_INDEX, INDEX_VERSION, MAX_PATCH_SIZE, translation_order,
)
from gamedb.exo.media import location_path, open_location
from gamedb.explorer.manuals import manual_location
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


def serve_vgm(handler, key):
    root = handler.server.vgm_root
    if root is None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    location = handler.server.repository.vgm_asset(key)
    if not location:
        return handler.send_error(HTTPStatus.NOT_FOUND)
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


@lru_cache(maxsize=4)
def _read_translation_index(path, revision):
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != INDEX_VERSION:
        return {}, {}
    records = {}
    by_signature = defaultdict(list)
    for record in document["translations"]:
        key = record["key"]
        if (not re.fullmatch(r"[0-9a-f]{64}", key) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                or record["format"] not in FORMATS or not 0 < record["size"] <= MAX_PATCH_SIZE):
            continue
        records[key] = record
        for signature in record["signatures"]:
            by_signature[signature].append(record)
    return records, by_signature


def _translation_index(root):
    path = root / TRANSLATION_INDEX
    try:
        stat = path.stat()
        return _read_translation_index(path, (stat.st_ino, stat.st_mtime_ns, stat.st_size))
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


def add_local_translations(game, root, platform="snes"):
    _, by_signature = _translation_index(root)
    for release in game["releases"]:
        if release["status"] != "matched":
            continue
        archives = release.get("archives", ())
        matches = {}
        for archive in archives:
            for record in by_signature.get(archive["signature"], ()):
                if record["key"] in matches or not _translation_location(root, record):
                    continue
                public = {field: value for field, value in record.items() if field != "signatures"}
                public["baseReleaseSignature"] = archive["signature"]
                public["url"] = f"/related-media/{platform}-translation/{record['key']}"
                if supports_patching(record["format"], record["layout"]):
                    public["romDownloadUrl"] = (
                        f"/api/v1/releases/{archive['signature']}/translations/{record['key']}/download"
                    )
                if len(archives) > 1:
                    public["baseArchive"] = archive["archiveNames"][0]
                matches[record["key"]] = public
        if matches:
            release["translations"] = sorted(matches.values(), key=translation_order)


def add_translation_availability(games, root):
    _, by_signature = _translation_index(root)
    available = {signature for signature, records in by_signature.items()
                 if any(_translation_location(root, record) for record in records)}
    for game in games:
        for release in game["releases"]:
            signatures = release.pop("archiveSignatures", ())
            release["hasTranslations"] = release["status"] == "matched" and not available.isdisjoint(signatures)


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


def serve_retail_translation_rom(handler, signature, key):
    from gamedb.explorer.server import _resolve_rom_path

    for platform, root in handler.server.retail_translation_roots.items():
        records, _ = _translation_index(root)
        record = records.get(key)
        if record and signature in record["signatures"]:
            break
    else:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    if not supports_patching(record["format"], record["layout"]):
        return handler._json_response({"error": "This patch requires a different ROM layout."}, HTTPStatus.CONFLICT)
    patch_location = _translation_location(root, record)
    if patch_location is None:
        return handler._json_response({"error": "The translation patch is unavailable."}, HTTPStatus.NOT_FOUND)

    rom = handler.server.repository.retail_translation_base(platform, signature, record["baseSha1"])
    if rom is None:
        return handler._json_response({"error": "The verified base ROM is unavailable."}, HTTPStatus.CONFLICT)
    try:
        path = _resolve_rom_path(handler.server.rom_root, rom["path"])
        with ZipFile(path) as archive, archive.open(rom["member_path"]) as member:
            original = member.read(MAX_ROM_SIZE + 1)
    except (BadZipFile, KeyError, NotImplementedError, OSError, RuntimeError, ValueError):
        return handler._json_response({"error": "The verified base ROM is unavailable."}, HTTPStatus.CONFLICT)
    if len(original) > MAX_ROM_SIZE or hashlib.sha1(original).hexdigest() != record["baseSha1"]:
        return handler._json_response({"error": "The base ROM checksum or size has changed."}, HTTPStatus.CONFLICT)

    try:
        with open_location(root, patch_location) as file:
            patch = file.read(record["size"] + 1)
    except (OSError, ValueError):
        return handler._json_response({"error": "The translation patch has changed."}, HTTPStatus.CONFLICT)
    if len(patch) != record["size"] or hashlib.sha256(patch).hexdigest() != record["sha256"]:
        return handler._json_response({"error": "The translation patch has changed."}, HTTPStatus.CONFLICT)
    try:
        patched = apply_translation(original, patch, record["format"], record["layout"],
                                    pad_to_size=record.get("padToSize"))
    except PatchError as error:
        return handler._json_response({"error": str(error)}, HTTPStatus.CONFLICT)

    base_name = Path(rom["member_path"].replace("\\", "/")).stem
    tag = " ".join(item for item in (record["language"], record["version"]) if item)
    extension = "md" if platform == "megadrive" else "sfc"
    filename = re.sub(r"[/\\\x00-\x1f\x7f]", "_", f"{base_name} [{tag}].{extension}")
    return _serve_file(handler, key, root, {
        "path": filename, "revision": hashlib.sha256(patched).hexdigest(),
        "locations": [{"size_bytes": len(patched), "member_no": 0}],
    }, force_download=True, open_media=lambda *_: BytesIO(patched), cache_control="private, no-store")


def _serve_file(handler, key, root, asset, revision=None, preview_size=None, *,
                force_download=False, open_media=open_location, preview_page=1, cache_control=None):
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
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
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
