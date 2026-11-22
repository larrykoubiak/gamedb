"""Serve source-owned catalog attachments and their artwork previews."""

import mimetypes
import shutil
import tempfile
from contextlib import ExitStack
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from stat import S_ISREG
from urllib.parse import quote, urlsplit
from zipfile import BadZipFile

from gamedb.catalog.snes_manuals import INDEX_NAME, manual_key, read_manual_index
from gamedb.exo.media import location_path, open_location
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


@lru_cache(maxsize=4)
def _manual_index(path, revision):
    return read_manual_index(path)


def _manual_location(root, key):
    if root is None:
        return None
    try:
        index = root / INDEX_NAME
        revision = index.stat()
        records = _manual_index(index, (revision.st_ino, revision.st_mtime_ns, revision.st_size))
        record = records.get(key)
        if not isinstance(record, dict) or not isinstance(relative := record.get("path"), str):
            return None
        path = location_path(root, relative)
        stat = path.stat()
        if (path.suffix.lower() != ".pdf" or not S_ISREG(stat.st_mode)
                or stat.st_size != record.get("size") or stat.st_mtime_ns != record.get("mtime_ns")):
            return None
    except (OSError, ValueError):
        return None
    return {"source_path": relative, "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "member_no": 0}


def add_local_manuals(game, root):
    for release in game["releases"]:
        for manual in release.get("manuals", ()):
            key = manual_key(manual["url"])
            if _manual_location(root, key):
                manual.update(
                    localUrl=f"/related-media/snes-manual/{key}",
                    preview=f"/previews/320/snes-manual/{key}",
                    format="PDF",
                )


def serve_snes_manual(handler, key, *, preview_size=None):
    root = handler.server.snes_manual_root
    location = _manual_location(root, key)
    if location is None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    return _serve_manual_file(handler, key, root, location, preview_size)


def serve_snes_manual_pages(handler, key, page=None):
    root = handler.server.snes_manual_root
    location = _manual_location(root, key)
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


def _serve_file(handler, key, root, asset, revision=None, preview_size=None, *,
                force_download=False, open_media=open_location, preview_page=1):
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
            "Cache-Control", "public, max-age=3600" if revision else "public, no-cache"
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
