#!/usr/bin/env python3
"""Convert Undub 7z/RAR archive sets to verified single ZIP files."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


PART_RAR = re.compile(r"^(?P<base>.+)\.part0*1\.rar$", re.IGNORECASE)
ANY_PART_RAR = re.compile(r"^(?P<base>.+)\.part\d+\.rar$", re.IGNORECASE)
OLD_RAR_VOLUME = re.compile(r"^(?P<base>.+)\.[r-z]\d\d$", re.IGNORECASE)


@dataclass(frozen=True)
class ArchiveSet:
    first: Path
    target: Path
    volumes: tuple[Path, ...]

    @property
    def source_size(self) -> int:
        return sum(path.stat().st_size for path in self.volumes)


def archive_set(first: Path) -> ArchiveSet:
    name = first.name
    lower = name.lower()
    siblings = tuple(path for path in first.parent.iterdir() if path.is_file())

    if lower.endswith(".7z.001"):
        base = name[:-7]
        volume_pattern = re.compile(re.escape(base) + r"\.7z\.\d{3}$", re.IGNORECASE)
        volumes = tuple(sorted(path for path in siblings if volume_pattern.fullmatch(path.name)))
    elif lower.endswith(".7z"):
        base = name[:-3]
        volumes = (first,)
    elif match := PART_RAR.fullmatch(name):
        base = match.group("base")
        volume_pattern = re.compile(re.escape(base) + r"\.part\d+\.rar$", re.IGNORECASE)
        volumes = tuple(sorted(path for path in siblings if volume_pattern.fullmatch(path.name)))
    elif lower.endswith(".rar") and not ANY_PART_RAR.fullmatch(name):
        base = name[:-4]
        volumes = tuple(sorted(
            path for path in siblings
            if path == first
            or (
                (match := OLD_RAR_VOLUME.fullmatch(path.name)) is not None
                and match.group("base").casefold() == base.casefold()
            )
        ))
    else:
        raise ValueError(f"not an archive-set start: {first}")

    return ArchiveSet(first, first.with_name(base + ".zip"), volumes)


def discover(root: Path) -> list[ArchiveSet]:
    starts: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if lower.endswith(".7z.001") or lower.endswith(".7z"):
            starts.append(path)
        elif PART_RAR.fullmatch(path.name):
            starts.append(path)
        elif lower.endswith(".rar") and not ANY_PART_RAR.fullmatch(path.name):
            starts.append(path)
    return [archive_set(path) for path in sorted(starts)]


def run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}\n{result.stdout[-20000:]}"
        )


def remove_obsolete_sfv(directory: Path, deleted_names: set[str]) -> None:
    folded = {name.casefold() for name in deleted_names}
    for sfv in directory.glob("*.sfv"):
        try:
            entries = {
                line.rsplit(maxsplit=1)[0].strip().casefold()
                for line in sfv.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip() and not line.lstrip().startswith(";") and len(line.rsplit(maxsplit=1)) == 2
            }
        except OSError:
            continue
        if entries & folded:
            try:
                sfv.unlink()
                print(f"removed obsolete {sfv}", flush=True)
            except FileNotFoundError:
                pass


def convert(item: ArchiveSet, root: Path, index: int, total: int) -> None:
    if item.target.exists():
        raise FileExistsError(f"target already exists: {item.target}")

    gib = item.source_size / 1024**3
    print(
        f"[{index}/{total}] {item.first.relative_to(root)} "
        f"({len(item.volumes)} volumes, {gib:.2f} GiB)",
        flush=True,
    )
    work = Path(tempfile.mkdtemp(prefix=".gamedb-undub-", dir=root))
    partial = item.target.with_name(f".{item.target.name}.gamedb-partial")
    try:
        run(["7z", "x", "-y", f"-o{work}", str(item.first)])
        children = sorted(work.iterdir())
        if not children:
            raise RuntimeError(f"archive extracted no files: {item.first}")
        run(
            ["7z", "a", "-tzip", "-mx=1", "-mmt=on", str(partial), "--", *(path.name for path in children)],
            cwd=work,
        )
        run(["7z", "t", str(partial)])
        os.replace(partial, item.target)
        deleted_names = {path.name for path in item.volumes}
        for volume in item.volumes:
            volume.unlink()
        remove_obsolete_sfv(item.first.parent, deleted_names)
        print(f"created {item.target.relative_to(root)}", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if partial.exists():
            partial.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()

    root = args.root.resolve()
    items = discover(root)
    collisions = [item.target for item in items if item.target.exists()]
    total_size = sum(item.source_size for item in items)
    print(f"found {len(items)} archive sets ({total_size / 1024**3:.2f} GiB)")
    if collisions:
        for path in collisions:
            print(f"collision: {path}")
        raise SystemExit("refusing to overwrite existing ZIP files")
    if not args.execute:
        print("dry run only; pass --execute to convert")
        return 0

    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [
            executor.submit(convert, item, root, index, len(items))
            for index, item in enumerate(items, 1)
        ]
        try:
            for future in concurrent.futures.as_completed(futures):
                future.result()
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
