"""Refresh the supported JoshW soundtrack collections on the VGM share."""

import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPSConnection, HTTPException
from pathlib import Path
from stat import S_ISREG
from tempfile import NamedTemporaryFile
from time import sleep
from urllib.parse import quote
from urllib.request import urlopen

from .joshw import COLLECTION, DOMAINS, INDEX_URL, PSF_COLLECTION, parse_path, platform, superseded_sources


def packages(index):
    buckets = defaultdict(list)
    seen = set()
    for row in index:
        domain, name = row["sd"], row["nm"]
        if domain not in DOMAINS or row.get("old"):
            continue
        path = parse_path(name)
        if domain == "cdi" and path.parts[0] != "jaguar":
            continue
        if not platform(domain, path):
            continue
        if path.suffix.casefold() not in {".7z", ".zip", ".gbs", ".mgb", ".sgc", ".kss", ".m3u"}:
            continue
        if (domain, path) in seen:
            raise ValueError(f"Duplicate JoshW path: {domain}/{name}")
        seen.add((domain, path))
        size = row["sz"]
        if type(size) is not int or size <= 0:
            raise ValueError(f"Invalid JoshW size for {domain}/{name}")
        # Use the index's minute stamp as the local revision, consistently
        # treating it as UTC because the index carries no timezone.
        revision = int(datetime.fromisoformat(row["md"]).replace(tzinfo=timezone.utc).timestamp())
        buckets[domain].append((path, size, revision))
    for entries in buckets.values():
        superseded = superseded_sources(path.as_posix() for path, _, _ in entries)
        entries[:] = [entry for entry in entries if entry[0].as_posix() not in superseded]
    return buckets


def same_version(path, size, revision):
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return False
    return S_ISREG(stat.st_mode) and stat.st_size == size and stat.st_mtime == revision


def package_destination(root, domain, path):
    destination = root / domain / path
    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
        raise ValueError(f"Invalid JoshW destination: {destination}")
    return destination


def link_playstation_packages(root, entries):
    """Reuse archives from the flat PSF collection that match the current index revision."""
    legacy = root.parent / PSF_COLLECTION
    linked = 0
    for path, size, revision in entries:
        destination = package_destination(root, "psf", path)
        source = legacy / path.name
        if destination.exists() or not same_version(source, size, revision):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.hardlink_to(source)
        except FileExistsError:
            continue
        linked += 1
    return linked


def fetch_file(connection, path, size, revision, destination):
    if same_version(destination, size, revision):
        return False
    connection.request("GET", "/" + quote(path.as_posix()), headers={"User-Agent": "GameDB VGM import"})
    with connection.getresponse() as response:
        if response.status != 200:
            raise OSError(f"HTTP {response.status}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=destination.parent, prefix=".joshw-", delete=False) as sink:
            temporary = Path(sink.name)
            try:
                received = 0
                while block := response.read(min(256 * 1024, size + 1 - received)):
                    received += len(block)
                    if received > size:
                        break
                    if received == len(block) and path.suffix.casefold() == ".7z" and not block.startswith(b"7z\xbc\xaf\x27\x1c"):
                        raise OSError("Invalid 7-Zip header")
                    sink.write(block)
                if received != size:
                    raise OSError(f"Expected {size} bytes, received {received}")
                sink.close()
                os.utime(temporary, (revision, revision))
                temporary.chmod(0o644)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
    return True


def fetch_bucket(root, domain, entries):
    connection = HTTPSConnection(f"{domain}.joshw.info", timeout=45)
    downloaded = failed = 0
    try:
        for number, (path, size, revision) in enumerate(entries, 1):
            destination = package_destination(root, domain, path)
            for attempt in range(3):
                try:
                    if fetch_file(connection, path, size, revision, destination):
                        downloaded += 1
                        sleep(0.1)
                    break
                except (OSError, HTTPException) as error:
                    connection.close()
                    if str(error) == "HTTP 429":
                        print(f"{domain}: upstream rate limit at {path}", file=sys.stderr, flush=True)
                        return len(entries) - number + 1 + failed
                    if attempt == 2 or str(error) == "HTTP 404":
                        print(f"{domain}: {path}: {error}", file=sys.stderr, flush=True)
                        failed += 1
                        break
                    sleep(2 ** attempt)
            if number % 100 == 0 or number == len(entries):
                print(f"{domain}: {number}/{len(entries)} checked, {downloaded} downloaded, {failed} failed", flush=True)
    finally:
        connection.close()
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="existing VGM library root")
    parser.add_argument("--index", type=Path, help="use a saved HCS64 index")
    parser.add_argument("--bucket", action="append", help="limit the scope to an index subdomain")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--download", action="store_true", help="write the packages onto the share")
    action.add_argument("--link-existing", action="store_true", help="hard-link matching local PSF archives into JoshW")
    args = parser.parse_args(argv)
    buckets = args.bucket or (["psf"] if args.link_existing else [])
    if args.link_existing and set(buckets) != {"psf"}:
        parser.error("--link-existing reuses PlayStation archives in bucket psf")
    if args.index:
        index = json.loads(args.index.read_bytes())
    else:
        with urlopen(INDEX_URL, timeout=30) as response:
            index = json.load(response)
    selected = packages(index)
    if buckets:
        unknown = set(buckets) - selected.keys()
        if unknown:
            parser.error(f"unsupported JoshW buckets: {', '.join(sorted(unknown))}")
        selected = {domain: selected[domain] for domain in dict.fromkeys(buckets)}
    else:
        for domain in ("psf", "dsf", "gcn", "psf2"):
            selected.pop(domain, None)
    if not selected:
        parser.error("no supported downloads found in the HCS64 index")
    for domain, entries in selected.items():
        print(f"{domain}: {len(entries)} files, {sum(size for _, size, _ in entries):,} bytes", flush=True)
    if not (args.download or args.link_existing):
        return 0
    if not args.root.is_dir():
        parser.error(f"VGM root is unavailable: {args.root}")
    collection = args.root.resolve() / COLLECTION
    if collection.is_symlink():
        parser.error(f"JoshW folder is a symbolic link: {collection}")
    if args.link_existing:
        linked = link_playstation_packages(collection, selected["psf"])
        print(f"psf: {linked} existing archives linked", flush=True)
        return 0
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(fetch_bucket, collection, domain, entries)
                   for domain, entries in selected.items()]
        failed = sum(result.result() for result in results)
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
