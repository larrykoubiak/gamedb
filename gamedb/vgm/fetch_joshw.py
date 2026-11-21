"""Fetch the current JoshW cartridge and handheld collections onto the VGM share."""

import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPSConnection, HTTPException
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import sleep
from urllib.parse import quote
from urllib.request import urlopen

from .joshw import COLLECTION, DOMAINS, INDEX_URL, parse_path, platform, superseded_sources


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


def fetch_file(connection, path, size, revision, destination):
    if destination.is_file():
        stat = destination.stat()
        if stat.st_size == size and stat.st_mtime == revision:
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
            destination = root / domain / path
            if destination.is_symlink() or not destination.resolve().is_relative_to(root):
                raise ValueError(f"Invalid JoshW destination: {destination}")
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
    parser.add_argument("--download", action="store_true", help="write the packages onto the share")
    args = parser.parse_args(argv)
    if args.index:
        index = json.loads(args.index.read_bytes())
    else:
        with urlopen(INDEX_URL, timeout=30) as response:
            index = json.load(response)
    selected = packages(index)
    if not selected:
        parser.error("no cartridge or handheld downloads found in the HCS64 index")
    if args.bucket:
        unknown = set(args.bucket) - selected.keys()
        if unknown:
            parser.error(f"unsupported JoshW buckets: {', '.join(sorted(unknown))}")
        selected = {domain: selected[domain] for domain in dict.fromkeys(args.bucket)}
    for domain, entries in selected.items():
        print(f"{domain}: {len(entries)} files, {sum(size for _, size, _ in entries):,} bytes", flush=True)
    if not args.download:
        return 0
    if not args.root.is_dir():
        parser.error(f"VGM root is unavailable: {args.root}")
    collection = args.root.resolve() / COLLECTION
    if collection.is_symlink():
        parser.error(f"JoshW folder is a symbolic link: {collection}")
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(fetch_bucket, collection, domain, entries)
                   for domain, entries in selected.items()]
        failed = sum(result.result() for result in results)
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
