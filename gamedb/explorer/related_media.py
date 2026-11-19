"""Serve source-owned catalog attachments and their artwork previews."""

import mimetypes
import os
import shutil
import tempfile
from contextlib import ExitStack
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, urlsplit
from zipfile import BadZipFile

from gamedb.exo.media import location_path, open_location


def serve(handler, key, *, revision=None, preview_size=None):
    from gamedb.explorer.server import _byte_range

    asset = handler.server.repository.exo_asset(key)
    if (
        not asset
        or revision
        and (asset["revision"] != revision or asset["kind"] != "artwork")
    ):
        return handler.send_error(HTTPStatus.NOT_FOUND)
    name = Path(asset["path"]).name
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
    root = handler.server.exo_root
    with ExitStack() as stack:
        for location in asset["locations"] or ():
            try:
                stream = stack.enter_context(open_location(root, location))
                break
            except (OSError, ValueError, BadZipFile):
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
                path = cache.get(original, preview_size)
                stream = stack.enter_context(path.open("rb"))
                size, mime = path.stat().st_size, "image/webp"
            except (OSError, ValueError, SyntaxError, BadZipFile):
                return handler.send_error(HTTPStatus.NOT_FOUND)
        etag = (
            f'"{asset["revision"]}-{key}-{preview_size or 0}-{location["member_no"]}"'
        )
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
        inline = (
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
        handler.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        handler.send_header(
            "Cache-Control", "public, max-age=3600" if revision else "public, no-cache"
        )
        handler.send_header("ETag", etag)
        handler.end_headers()
        while remaining:
            data = stream.read(min(remaining, 1024 * 1024))
            if not data:
                break
            handler.wfile.write(data)
            remaining -= len(data)
