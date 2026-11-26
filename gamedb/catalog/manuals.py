"""Mirror the manual files linked by a retail catalog."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
import fcntl
from hashlib import sha1, sha256
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import sleep
import unicodedata
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from gamedb.config import PROJECT_ROOT
from gamedb.exo.media import location_path

from .references import read_index


INDEX_NAME = ".gamedb-manuals.json"
SOURCE_REFERENCES = PROJECT_ROOT / "reference/snes_retail_manual_files.json"
MARKET_DIRECTORIES = {
    "JP": "Japan", "NA": "North America", "PAL": "PAL", "BR": "Brazil", "KR": "South Korea", "AS": "Asia",
    "MVS": "MVS", "AES": "AES",
}
USER_AGENT = "GameDB/2.0 (retail manual library)"
CHUNK_SIZE = 1024 * 1024


def manual_key(url):
    return sha256(url.encode()).hexdigest()


def read_manual_index(path):
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("manuals"), dict):
        raise ValueError("Invalid GameDB manual index")
    return data["manuals"]


def _write_index(root, records):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump({"version": 1, "manuals": records}, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.close()
            temporary.chmod(0o644)
            temporary.replace(root / INDEX_NAME)
        finally:
            temporary.unlink(missing_ok=True)


def _file_name(name, key):
    name = unicodedata.normalize("NFC", name).removesuffix(".pdf")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name)
    name = " ".join(name.split()).strip(" .")
    stem = name.encode()[:180].decode(errors="ignore") or "Manual"
    return f"{stem} [{key[:12]}].pdf"


def _catalog_manuals(path):
    with path.open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    manuals = {}
    for game in catalog["games"]:
        for release in game["releases"]:
            for manual in release.get("manuals", ()):
                key = manual_key(manual["url"])
                path = Path(MARKET_DIRECTORIES[release["market"]], _file_name(manual["name"], key))
                manuals.setdefault(key, (path, manual))
    return manuals


def _archive_files(item, cache):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", item):
        raise ValueError("Invalid Internet Archive item name")
    index = read_index(cache / f"{item}.json", f"https://archive.org/metadata/{item}")
    data = json.loads(index.content)
    if data.get("metadata", {}).get("identifier") != item:
        raise ValueError("Internet Archive item metadata unavailable")
    return [file for file in data.get("files", ()) if file.get("private") not in ("true", True)]


def _archive_file(item, file):
    return f"https://archive.org/download/{item}/{quote(file['name'])}", file.get("sha1"), int(file["size"])


def _archive_pdf(item, name, files):
    files = [file for file in files if file["name"].lower().endswith(".pdf")]
    candidates = [file for file in files if file.get("source") == "original"] or files
    if len(candidates) > 1:
        candidates = [file for file in candidates
                      if not re.search(r"\s+\((?:Searchable|Clearscan)\)\.pdf$", file["name"], re.I)] or candidates
    if len(candidates) > 1:
        matches = [file for file in candidates if "manual" in file["name"].lower()]
        if len(matches) == 1:
            candidates = matches
    if len(candidates) != 1:
        raise ValueError(f"No unique PDF in Internet Archive item for {name}")
    (file,) = candidates
    return _archive_file(item, file)


def _sources(manual, cache, reviewed):
    if "pdf" in reviewed:
        return [(reviewed["pdf"], reviewed.get("sha1"), reviewed.get("size"))], False
    if "pages" in reviewed:
        return [(url, None, None) for url in reviewed["pages"]], True
    url = manual["url"]
    location = urlsplit(url)
    hostname = location.hostname or ""
    if location.scheme != "https" or (hostname not in {
        "archive.org", "www.gamingalexandria.com", "www.nintendo.co.jp", "segaretro.org", "www.digitpress.com",
        "www.videogamemanual.com", "rq87.flyingomelette.com", "www.jamma-nation-x.com",
        "necretro.org", "retrocdn.net", "dds.konami.com", "www.pcengine.co.uk", "www.videogameden.com",
        "cdn-ak.f.st-hatena.com", "cdn.rwemulator.com", "www.emulation64.fr", "emulation64.fr",
        "drive.usercontent.google.com", "goldeneyedepot.com", "m1.nintendo.net", "www.nintendo.com", "bdjogos.com.br",
        "db.hfsplay.fr", "static.atariage.com", "www.gamesdatabase.org", "odyssey2.info", "www.odyssey2.info",
        "play-sc-3000.online",
    } and not hostname.endswith(".archive.org")):
        raise ValueError("Unsupported manual source URL")
    if "pages" in manual:
        pages = manual["pages"]
        if not pages or any(page.scheme != "https" or page.netloc != location.netloc for page in map(urlsplit, pages)):
            raise ValueError("Manual page scans must use the same HTTPS origin")
        return [(page, None, None) for page in pages], True
    if hostname == "archive.org" and location.path.startswith("/details/"):
        item = location.path.split("/")[2]
        files = _archive_files(item, cache)
        if "archivePages" in reviewed:
            by_name = {file["name"]: file for file in files if file.get("source") == "original"}
            if any(name not in by_name for name in reviewed["archivePages"]):
                raise ValueError("A reviewed manual page is missing from the scan")
            return [_archive_file(item, by_name[name]) for name in reviewed["archivePages"]], True
        return [_archive_pdf(item, manual["name"], files)], False
    return [(url, manual.get("sha1"), manual.get("size"))], False


def _verify_bytes(count, expected_size, digest, expected_digest):
    if expected_size is not None and count != expected_size:
        raise ValueError(f"Expected {expected_size} bytes, received {count}")
    if expected_digest and digest != expected_digest:
        raise ValueError("File checksum differs from the source")


def _verify_pdf(stream, count):
    stream.seek(0)
    if not stream.read(1024).lstrip().startswith(b"%PDF-"):
        raise ValueError("Manual source did not return a PDF")
    stream.seek(max(0, count - 65536))
    if b"%%EOF" not in stream.read():
        raise ValueError("Incomplete PDF")


def _copy_source(file, stream):
    url, expected_digest, expected_size = file
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=45) as source:
        if source.status != 200:
            raise ValueError(f"Expected the complete file, received HTTP {source.status}")
        if expected_size is None and source.headers.get("Content-Length"):
            expected_size = int(source.headers["Content-Length"])
        digest = sha1()
        while chunk := source.read(CHUNK_SIZE):
            stream.write(chunk)
            digest.update(chunk)
    size, checksum = stream.tell(), digest.hexdigest()
    _verify_bytes(size, expected_size, checksum, expected_digest)
    return size, checksum


def _copy_tosec_manual(relative, stream):
    rom_root = Path(os.environ.get("GAMEDB_ROM_ROOT") or "/mnt/synology")
    path = location_path(rom_root / "roms/TOSEC-PIX", relative)
    try:
        with ZipFile(path) as archive:
            pdfs = [member for member in archive.infolist() if member.filename.lower().endswith(".pdf")]
            if len(pdfs) != 1 or not 0 < pdfs[0].file_size <= 128 * 1024**2:
                raise ValueError("Expected one PDF in the local manual archive")
            with archive.open(pdfs[0]) as source:
                while chunk := source.read(CHUNK_SIZE):
                    stream.write(chunk)
    except (BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError("Could not read the local manual archive") from error
    return _measure(stream)


def _measure(stream):
    stream.seek(0)
    digest = sha1()
    while chunk := stream.read(CHUNK_SIZE):
        digest.update(chunk)
    return stream.tell(), digest.hexdigest()


def _assemble_scan(files, output, name):
    from PIL import Image, ImageOps

    with TemporaryDirectory(prefix="gamedb-manual-") as directory, ExitStack() as images:
        pages = []
        for index, file in enumerate(files):
            raw = Path(directory) / "page"
            with raw.open("wb") as stream:
                _copy_source(file, stream)
            with Image.open(raw) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
                page = Path(directory) / f"{index}.jpg"
                image.convert("RGB").save(page, "JPEG", quality=92)
            pages.append(images.enter_context(Image.open(page)))
        pages[0].save(output, "PDF", save_all=True, append_images=pages[1:],
                      resolution=200, title=name, quality=92)
    return _measure(output)


def _save_manual(path, files, scan, name, *, local_archive=None):
    with NamedTemporaryFile(dir=path.parent, prefix=".manual-", suffix=".part", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            if local_archive:
                size, checksum = _copy_tosec_manual(local_archive, stream)
            elif scan:
                size, checksum = _assemble_scan(files, stream, name)
            else:
                size, checksum = _copy_source(files[0], stream)
            _verify_pdf(stream, size)
            stream.close()
            temporary.chmod(0o644)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return size, checksum


def _existing_pdf(path, expected_digest, expected_size):
    try:
        with path.open("rb") as stream:
            size, digest = _measure(stream)
            _verify_pdf(stream, size)
            _verify_bytes(size, expected_size, digest, expected_digest)
    except (FileNotFoundError, ValueError):
        return None
    return size, digest


def _sync_manual(root, record, relative, manual, cache, reviewed):
    path = root / relative
    if record and record.get("path") == relative.as_posix() and path.is_file():
        stat = path.stat()
        if stat.st_size == record.get("size") and stat.st_mtime_ns == record.get("mtime_ns"):
            if not manual.get("sha1") or record.get("sha1") == manual["sha1"]:
                return "reused", record
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            local_archive = manual.get("localArchive")
            files, scan = ([(manual["url"], None, None)], False) if local_archive else _sources(manual, cache, reviewed)
            _, expected_digest, expected_size = files[0] if not scan else (None, None, None)
            if existing := _existing_pdf(path, expected_digest, expected_size):
                size, digest = existing
                status = "reused"
            else:
                size, digest = _save_manual(path, files, scan, manual["name"], local_archive=local_archive)
                status = "downloaded"
            return status, {"path": relative.as_posix(), "size": size, "sha1": digest,
                            "mtime_ns": path.stat().st_mtime_ns, "source": manual["url"],
                            "retrievedFrom": reviewed.get("sourcePage") or files[0][0]}
        except (OSError, HTTPException, ValueError) as error:
            if attempt == 2 or (isinstance(error, HTTPError) and 400 <= error.code < 500
                                and error.code not in {408, 429}):
                raise
            delay = error.headers.get("Retry-After", "") if isinstance(error, HTTPError) else ""
            sleep(min(int(delay), 60) if delay.isdecimal() else 2 ** attempt)


def sync_manuals(catalog, root, cache, *, workers=8, source_references=SOURCE_REFERENCES):
    manuals = _catalog_manuals(catalog)
    reviewed = json.loads(source_references.read_text(encoding="utf-8")) if source_references else {}
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".gamedb-manuals.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for directory in MARKET_DIRECTORIES.values():
            for partial in (root / directory).glob(".manual-*.part"):
                partial.unlink(missing_ok=True)
        index = root / INDEX_NAME
        records = read_manual_index(index) if index.is_file() else {}
        initial = {key: records[key] for key in manuals.keys() & records.keys()}
        counts, failures = Counter(), {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = {pool.submit(_sync_manual, root, initial.get(key), relative, manual, cache,
                                reviewed.get(manual["url"], {})): (key, manual)
                    for key, (relative, manual) in manuals.items()}
            for completed, job in enumerate(as_completed(jobs), 1):
                key, manual = jobs[job]
                try:
                    status, record = job.result()
                    records[key] = record
                    counts[status] += 1
                except (OSError, HTTPException, ValueError) as error:
                    failures[manual["url"]] = str(error)
                    records.pop(key, None)
                    print(f"{manual['name']}: {error}", file=sys.stderr, flush=True)
                if completed == 1 or completed % 25 == 0:
                    _write_index(root, records)
                    print(f"Manuals {completed}/{len(manuals)} · {sum(counts.values())} saved · "
                          f"{len(failures)} unavailable", file=sys.stderr, flush=True)
        _write_index(root, records)
    return {"total": len(manuals), "downloaded": counts["downloaded"], "reused": counts["reused"],
            "bytes": sum(records[key]["size"] for key in manuals.keys() & records.keys()),
            "failures": failures}
