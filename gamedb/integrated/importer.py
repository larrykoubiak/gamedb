"""Scan reviewed integrated ZIPs and atomically replace their staging snapshot."""

from __future__ import annotations

import csv
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
import uuid
import zipfile

from sqlalchemy import delete, insert, text
from sqlalchemy.engine import Engine

from . import schema


REGION_LABELS = {"US": "USA", "EU": "Europe", "JP": "Japan"}


@dataclass(frozen=True)
class ManifestRow:
    platform_directory: str
    release_directory: str
    title: str
    manufacturer: str
    system: str
    region: str
    modification: str
    variant: str | None
    zip_pattern: str


@dataclass(frozen=True)
class Package:
    path: Path
    relative_path: str
    manifest: ManifestRow
    media_sequence: int | None
    media_total: int | None

    @property
    def archive_name(self) -> str:
        label = REGION_LABELS[self.manifest.region]
        modification = self.manifest.modification.title()
        variant = f" by {self.manifest.variant}" if self.manifest.variant else ""
        media = (
            f" (Disc {self.media_sequence} of {self.media_total})"
            if self.media_sequence is not None else ""
        )
        return (
            f"{self.manifest.title} ({label}) "
            f"[{modification}{variant}] [{self.manifest.system}]{media}.zip"
        )


class IntegratedImporter:
    """Import only packages selected by the reviewed manifest."""

    def __init__(
        self, engine: Engine, root: Path, manifest: Path, jobs: int = 1,
    ):
        self.engine = engine
        self.root = root.resolve()
        self.manifest_path = manifest.resolve()
        if jobs < 1:
            raise ValueError("jobs must be at least 1")
        self.jobs = jobs

    def execute(self) -> dict[str, int | str]:
        rows = self._manifest()
        packages = self._packages(rows)
        run_id = uuid.uuid4()
        imported_at = datetime.now(timezone.utc)
        package_rows = []
        file_rows = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.jobs
        ) as executor:
            scans = executor.map(
                self._members, (package.path for package in packages)
            )
            for index, (package, members) in enumerate(
                zip(packages, scans), 1
            ):
                package_rows.append({
                    "relative_path": package.relative_path,
                    "import_run_id": run_id,
                    "imported_at": imported_at,
                    "source_manufacturer": package.manifest.manufacturer,
                    "source_system": package.manifest.system,
                    "title": package.manifest.title,
                    "region": package.manifest.region,
                    "modification": package.manifest.modification,
                    "variant": package.manifest.variant,
                    "catalog_archive_name": package.archive_name,
                    "media_type": "disc" if package.media_sequence else None,
                    "media_part": (
                        str(package.media_sequence)
                        if package.media_sequence else None
                    ),
                    "media_sequence": package.media_sequence,
                    "media_total": package.media_total,
                    "archive_size": package.path.stat().st_size,
                })
                file_rows.extend({
                    "package_relative_path": package.relative_path,
                    **member,
                } for member in members)
                print(
                    f"[{index}/{len(packages)}] {package.relative_path}: "
                    f"{len(members):,} files",
                    flush=True,
                )

        with self.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
            schema.metadata.create_all(connection)
            connection.execute(delete(schema.integrated_file))
            connection.execute(delete(schema.integrated_package))
            connection.execute(insert(schema.integrated_package), package_rows)
            for start in range(0, len(file_rows), 2_000):
                connection.execute(
                    insert(schema.integrated_file), file_rows[start:start + 2_000]
                )
        return {
            "run_id": str(run_id),
            "packages": len(package_rows),
            "files": len(file_rows),
        }

    def _manifest(self) -> list[ManifestRow]:
        with self.manifest_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = [ManifestRow(
                platform_directory=row["platform_directory"].strip(),
                release_directory=row["release_directory"].strip(),
                title=row["title"].strip(),
                manufacturer=row["manufacturer"].strip(),
                system=row["system"].strip(),
                region=row["region"].strip(),
                modification=row["modification"].strip(),
                variant=row["variant"].strip() or None,
                zip_pattern=row["zip_pattern"].strip() or "*.zip",
            ) for row in csv.DictReader(handle)]
        if not rows:
            raise ValueError("integrated release manifest is empty")
        for row in rows:
            if row.region not in REGION_LABELS:
                raise ValueError(f"unknown region {row.region!r} for {row.title}")
            if row.modification not in {"undub", "fixed", "modified"}:
                raise ValueError(
                    f"unknown modification {row.modification!r} for {row.title}"
                )
        return rows

    def _packages(self, rows: list[ManifestRow]) -> list[Package]:
        result = []
        selected_paths: set[Path] = set()
        archive_names: set[str] = set()
        for row in rows:
            directory = self.root / row.platform_directory / row.release_directory
            paths = sorted(path for path in directory.glob(row.zip_pattern) if path.is_file())
            if not paths:
                raise FileNotFoundError(
                    f"{row.title!r} selects no ZIPs with {row.zip_pattern!r}"
                )
            grouped = len(paths) > 1
            sequences = list(range(1, len(paths) + 1)) if grouped else [None]
            for path, sequence in zip(paths, sequences):
                resolved = path.resolve()
                if resolved in selected_paths:
                    raise ValueError(f"ZIP selected more than once: {resolved}")
                selected_paths.add(resolved)
                package = Package(
                    path=resolved,
                    relative_path=resolved.relative_to(self.root).as_posix(),
                    manifest=row,
                    media_sequence=sequence if grouped else None,
                    media_total=len(paths) if grouped else None,
                )
                if package.archive_name in archive_names:
                    raise ValueError(
                        f"duplicate generated archive name: {package.archive_name}"
                    )
                archive_names.add(package.archive_name)
                result.append(package)
        return sorted(result, key=lambda item: item.relative_path)

    @staticmethod
    def _members(path: Path) -> list[dict[str, object]]:
        rows = []
        with zipfile.ZipFile(path) as archive:
            for member_index, info in enumerate(archive.infolist(), 1):
                if info.is_dir():
                    continue
                digest = hashlib.sha1()
                with archive.open(info) as source:
                    while block := source.read(1024 * 1024):
                        digest.update(block)
                member_path = info.filename.replace("\\", "/")
                rows.append({
                    "member_index": member_index,
                    "member_path": member_path,
                    "file_name": PurePosixPath(member_path).name,
                    "size": info.file_size,
                    "crc_hex": f"{info.CRC:08x}",
                    "sha1_hex": digest.hexdigest(),
                    "crc_verified": True,
                })
        if not rows:
            raise ValueError(f"ZIP contains no files: {path}")
        return rows
