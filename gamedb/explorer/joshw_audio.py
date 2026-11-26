"""Cache and play the JoshW archives selected in the retail catalog."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from http import HTTPStatus
from http.client import HTTPSConnection
import json
import os
from pathlib import PurePosixPath
import re
from shutil import disk_usage, rmtree
from threading import Lock
from urllib.parse import unquote, urlsplit

from sqlalchemy.exc import SQLAlchemyError

from gamedb.catalog.retail import write_report
from gamedb.explorer.related_media import serve_vgm_file
from gamedb.explorer.soundtrack_audio import flac_formats
from gamedb.vgm.fetch_joshw import fetch_file, same_version
from gamedb.vgm.inventory import Soundtrack, asset_for, key_for, tracks_for_set
from gamedb.vgm.joshw import COLLECTION, DEFAULT_SYSTEMS, SIXTH_GENERATION_BUCKETS, parse_path


_PLATFORMS = "|".join(SIXTH_GENERATION_BUCKETS)
JOSHW_AUDIO_PATH = re.compile(rf"/related-media/joshw/({_PLATFORMS})/([0-9a-f]{{32}})/([0-9a-f]{{64}})"
                             r"(?:/([0-9a-f]{64}))?")
_WORKERS = 2
_CACHE_BYTES = 16 * 1024**3


@dataclass(frozen=True)
class ArchiveSource:
    bucket: str
    path: PurePosixPath
    size: int
    revision: int

    @classmethod
    def from_catalog(cls, platform, record):
        bucket = SIXTH_GENERATION_BUCKETS[platform]
        url = urlsplit(record["url"])
        if (url.scheme != "https" or url.netloc != f"{bucket}.joshw.info"
                or url.query or url.fragment):
            raise ValueError("Invalid JoshW soundtrack source")
        path = parse_path(unquote(url.path[1:]))
        size, revision = record["size"], record["revision"]
        if (path.suffix.casefold() not in {".7z", ".zip"} or type(size) is not int
                or not 0 < size <= _CACHE_BYTES or type(revision) is not int or revision <= 0):
            raise ValueError("Invalid JoshW soundtrack archive")
        return cls(bucket, path, size, revision)

    @property
    def key(self):
        return key_for(self.bucket, self.path.as_posix(), str(self.size), str(self.revision))


class JoshwAudioCache:
    def __init__(self, root, library):
        self.root = root / "joshw-audio"
        self.library = library
        self.jobs = OrderedDict()
        self.lock = Lock()
        self.workers = ThreadPoolExecutor(max_workers=_WORKERS)

    def _archive(self, source):
        if self.library:
            local = self.library / COLLECTION / source.bucket / source.path
            if same_version(local, source.size, source.revision):
                return local
        return self.root / source.key / source.path.name

    def ready(self, source):
        directory = self.root / source.key
        archive = self._archive(source)
        if not same_version(archive, source.size, source.revision):
            return None
        try:
            manifest = directory / "assets.json"
            assets = json.loads(manifest.read_text(encoding="utf-8"))
            os.utime(manifest)
        except (OSError, ValueError):
            return None
        return archive.parent, assets

    def request(self, source, *, start):
        with self.lock:
            job = self.jobs.get(source.key)
            if job and not job.done():
                return HTTPStatus.ACCEPTED, None
            if ready := self.ready(source):
                return HTTPStatus.OK, ready
            if not start:
                status = HTTPStatus.BAD_GATEWAY if job else HTTPStatus.NOT_FOUND
                return status, None
            active = {key for key, future in self.jobs.items() if not future.done()}
            if len(active) >= _WORKERS:
                return HTTPStatus.SERVICE_UNAVAILABLE, None
            while len(self.jobs) >= 32:
                oldest = next(key for key in self.jobs if key not in active)
                del self.jobs[oldest]
            self.jobs[source.key] = self.workers.submit(self._prepare, source)
            return HTTPStatus.ACCEPTED, None

    def _prepare(self, source):
        directory = self.root / source.key
        directory.mkdir(parents=True, exist_ok=True)
        archive = self._archive(source)
        if not same_version(archive, source.size, source.revision):
            with self.lock:
                self._make_space(source)
            connection = HTTPSConnection(f"{source.bucket}.joshw.info", timeout=40)
            try:
                fetch_file(connection, source.path, source.size, source.revision, archive)
            finally:
                connection.close()
        package = asset_for(archive.name, archive.stat())
        album = Soundtrack(source.key, COLLECTION, archive.name, archive.stem,
                           DEFAULT_SYSTEMS[source.bucket], assets=[package])
        tracks_for_set(archive.parent, album)
        if album.issues:
            raise ValueError("Could not read the soundtrack archive")
        write_report(directory / "assets.json", album.assets)

    def _make_space(self, source):
        entries = []
        for directory in self.root.iterdir():
            if (not re.fullmatch(r"[0-9a-f]{64}", directory.name) or directory.is_symlink()
                    or directory.name == source.key or not directory.is_dir()
                    or (directory.name in self.jobs and not self.jobs[directory.name].done())):
                continue
            manifest = directory / "assets.json"
            used = sum(path.stat().st_size for path in directory.iterdir() if path.is_file())
            stamp = manifest.stat().st_mtime if manifest.is_file() else directory.stat().st_mtime
            entries.append((stamp, used, directory))
        remaining = sum(used for _, used, _ in entries) + source.size
        for _, used, directory in sorted(entries):
            if remaining <= _CACHE_BYTES:
                break
            rmtree(directory)
            remaining -= used
        if disk_usage(self.root).free < source.size:
            raise OSError("Soundtrack cache has insufficient free space")


def _album(record, source, assets):
    fields = ("name", "format", "kind", "playable")
    conversions = flac_formats()
    tracks = []
    for asset in assets:
        url = f"{record['loadUrl']}/{asset['key']}"
        item = {field: asset[field] for field in fields}
        item["url"] = url
        if asset["kind"] == "track" and asset["format"] in conversions:
            item["playbackUrl"] = url + "?audio=flac"
        tracks.append(item)
    return {
        "key": source.key, "title": record["title"].removesuffix(" — JoshW archive"),
        "collection": COLLECTION, "releases": record["releases"], "titleMatches": record["releases"],
        "sourceUrl": record["url"],
        "assets": tracks,
    }


def cached_joshw_albums(cache, platform, game):
    albums = []
    for record in game.get("soundtrackSources", ()):
        if not record.get("loadUrl"):
            continue
        try:
            source = ArchiveSource.from_catalog(platform, record)
            if ready := cache.ready(source):
                albums.append(_album(record, source, ready[1]))
        except (KeyError, OSError, ValueError):
            continue
    return albums


def serve_joshw_audio(handler, platform, game_key, key, asset_key=None, *, start=False, flac=False):
    if start and asset_key is not None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    try:
        catalog = handler.server.repository.retail_catalog(platform, game_key=game_key)
    except SQLAlchemyError:
        return handler.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
    if not catalog:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    game = catalog["game"]
    record = next((source for source in game.get("soundtrackSources", ())
                   if source.get("loadUrl") and sha256(source["url"].encode()).hexdigest() == key), None)
    if record is None:
        return handler.send_error(HTTPStatus.NOT_FOUND)
    try:
        source = ArchiveSource.from_catalog(platform, record)
    except (KeyError, ValueError):
        return handler.send_error(HTTPStatus.NOT_FOUND)
    cache = handler.server.joshw_audio
    if asset_key:
        if ready := cache.ready(source):
            root, assets = ready
            for asset in assets:
                if asset["key"] == asset_key:
                    cache_key = key_for(source.key, asset_key)
                    return serve_vgm_file(handler, root, cache_key, asset, flac=flac)
        return handler.send_error(HTTPStatus.NOT_FOUND)
    status, ready = cache.request(source, start=start)
    if ready:
        return handler._json_response(_album(record, source, ready[1]))
    messages = {
        HTTPStatus.ACCEPTED: "Preparing soundtrack…",
        HTTPStatus.BAD_GATEWAY: "The soundtrack archive could not be loaded.",
        HTTPStatus.NOT_FOUND: "The soundtrack hasn't been loaded yet.",
        HTTPStatus.SERVICE_UNAVAILABLE: "The soundtrack cache is busy. Try again shortly.",
    }
    return handler._json_response({"message": messages[status]}, status)
