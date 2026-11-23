"""Resolve mirrored retail manuals and warm their Explorer previews."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import os
from pathlib import Path
from stat import S_ISREG
from subprocess import DEVNULL, PIPE, Popen
import sys
from threading import Timer

from PIL import Image

from gamedb.catalog.manuals import INDEX_NAME, read_manual_index
from gamedb.exo.media import location_path
from gamedb.explorer.previews import source_revision


def manual_roots():
    snes = os.environ.get("GAMEDB_SNES_MANUAL_ROOT")
    megadrive = os.environ.get("GAMEDB_MEGADRIVE_MANUAL_ROOT") or "/mnt/synology/photo/Manuals/Mega Drive"
    nes = os.environ.get("GAMEDB_NES_MANUAL_ROOT") or "/mnt/synology/photo/Manuals/NES"
    return {"snes": Path(snes) if snes else None, "megadrive": Path(megadrive), "nes": Path(nes)}


@lru_cache(maxsize=4)
def _cached_index(path, revision):
    return read_manual_index(path)


def _manual_index(root):
    index = root / INDEX_NAME
    stat = index.stat()
    return _cached_index(index, (stat.st_ino, stat.st_mtime_ns, stat.st_size))


def _indexed_pdf(root, record):
    if not isinstance(record, dict) or not isinstance(relative := record.get("path"), str):
        raise ValueError("Manual is missing from the index")
    source = location_path(root, relative)
    stat = source.stat()
    if source.suffix.lower() != ".pdf" or not S_ISREG(stat.st_mode):
        raise ValueError("Manual is unavailable")
    if stat.st_size != record.get("size") or stat.st_mtime_ns != record.get("mtime_ns"):
        raise ValueError("Manual has changed since indexing")
    return source, stat


def manual_location(root, key):
    if root is None:
        return None
    try:
        record = _manual_index(root).get(key)
        _, stat = _indexed_pdf(root, record)
    except (OSError, ValueError):
        return None
    return {"source_path": record["path"], "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "member_no": 0}


def _read_page(stream, size):
    if stream.readline(64) != b"P6\n":
        raise ValueError("Poppler did not return a page image")
    width, height = map(int, stream.readline(64).split())
    if not (0 < width <= size and 0 < height <= size) or stream.readline(64) != b"255\n":
        raise ValueError("Unexpected page raster dimensions")
    length = width * height * 3
    pixels = stream.read(length)
    if len(pixels) != length:
        raise ValueError("Incomplete page raster")
    return Image.frombytes("RGB", (width, height), pixels)


def _render_pages(source, revision, pending, cache):
    first, last = min(pending), max(pending)
    size = cache.MANUAL_PAGE_SIZE
    # One Poppler process reads the PDF and streams uncompressed pages for WebP encoding.
    command = ["pdftoppm", "-q", "-f", str(first), "-l", str(last), "-scale-to", str(size), str(source)]
    with Popen(command, stdout=PIPE, stderr=DEVNULL) as process:
        timer = Timer(20 * (last - first + 1), process.kill)
        timer.daemon = True
        timer.start()
        try:
            for page in range(first, last + 1):
                with _read_page(process.stdout, size) as image:
                    target = pending.get(page)
                    if target is None or target.is_file():
                        continue
                    if source_revision(source.stat()) != revision:
                        raise ValueError("Manual changed during rendering")
                    cache.write_preview(target, image, size)
            if process.stdout.read(1) or process.wait():
                raise ValueError("Unexpected end of page rendering")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()


def _warm_manual(root, record, cache):
    source, stat = _indexed_pdf(root, record)
    revision = source_revision(stat)
    count = len(cache.manual_pages(source, (stat.st_size, stat.st_mtime_ns)))
    cache.get(source, 320)
    size = cache.MANUAL_PAGE_SIZE
    pending = {}
    for page in range(1, count + 1):
        target = cache.path_for(source, size, revision, page=page)
        if not target.is_file():
            pending[page] = target
    if pending:
        try:
            _render_pages(source, revision, pending, cache)
        except (OSError, ValueError):
            if source_revision(source.stat()) != revision:
                raise ValueError("Manual changed during rendering")
            for page, target in pending.items():
                if not target.is_file():
                    cache.get(source, size, page=page)
    if source_revision(source.stat()) != revision:
        raise ValueError("Manual changed during rendering")
    return count


def warm_manual_cache(root, cache, *, workers=3):
    records = _manual_index(root)
    if not records:
        raise ValueError("The manual index is empty")
    total = len(records)
    covers, pages, failures = 0, 0, {}
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        jobs = {pool.submit(_warm_manual, root, record, cache): key for key, record in records.items()}
        for completed, job in enumerate(as_completed(jobs), 1):
            try:
                pages += job.result()
                covers += 1
            except (OSError, ValueError, SyntaxError) as error:
                key = jobs[job]
                record = records[key]
                name = record.get("path", key) if isinstance(record, dict) else key
                failures[name] = str(error)
                print(f"Could not warm {name} ({error})", file=sys.stderr, flush=True)
            if completed == 1 or completed % 25 == 0 or completed == total:
                print(f"Manuals {completed}/{total} · {pages} pages ready · {len(failures)} unavailable",
                      file=sys.stderr, flush=True)
    finally:
        pool.shutdown(cancel_futures=True)
    return {"manuals": total, "covers": covers, "pages": pages, "failures": failures}
