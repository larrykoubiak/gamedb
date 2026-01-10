"""Import .rdb files into the database."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rdb.reader import Rdb
from app.db.models import Attribute, Release, Rom, System, Title


KNOWN_FIELDS = {
    "name",
    "description",
    "region",
    "releaseyear",
    "releasemonth",
    "serial",
    "rom_name",
    "size",
    "crc",
    "md5",
    "sha1",
}


@dataclass
class ImportStats:
    systems: int = 0
    titles: int = 0
    releases: int = 0
    roms: int = 0
    attributes: int = 0
    skipped_rows: int = 0
    skipped_fields: int = 0


class RdbImporter:
    def __init__(
        self,
        session: Session,
        source: str = "libretro_rdb",
        skipped_log_path: Optional[str] = None,
    ):
        self.session = session
        self.source = source
        self.skipped_log_path = skipped_log_path

    def import_path(self, path: str, limit: Optional[int] = None) -> ImportStats:
        stats = ImportStats()
        if os.path.isdir(path):
            entries = [e for e in sorted(os.listdir(path)) if e.endswith(".rdb")]
            for idx, entry in enumerate(entries, start=1):
                print(f"[import] {idx}/{len(entries)} {entry}")
                if entry.endswith(".rdb"):
                    stats = self._merge_stats(stats, self.import_file(os.path.join(path, entry), limit))
        else:
            stats = self.import_file(path, limit)
        return stats

    def import_file(self, path: str, limit: Optional[int] = None) -> ImportStats:
        stats = ImportStats()
        print(f"[import] loading {path}")
        table = Rdb.load(path)
        system_name = os.path.splitext(os.path.basename(path))[0]
        system = self._get_or_create_system(system_name, stats)

        for idx, row in enumerate(table.rows):
            if limit is not None and idx >= limit:
                break
            title_name = row.get("name")
            if not title_name:
                stats.skipped_rows += 1
                self._log_skipped_row(path, system_name, idx, row)
                continue

            title = self._get_or_create_title(system.id, title_name, row.get("description"), stats)
            release = self._get_or_create_release(title.id, row, stats)
            self._get_or_create_rom(release.id, row, stats)
            self._store_attributes(release.id, row, stats)
            if (idx + 1) % 5000 == 0:
                print(f"[import] {system_name}: {idx + 1} rows processed")

        self.session.commit()
        return stats

    def _get_or_create_system(self, name: str, stats: ImportStats) -> System:
        system = self.session.execute(
            select(System).where(System.name == name)
        ).scalar_one_or_none()
        if system:
            return system
        system = System(name=name)
        self.session.add(system)
        self.session.flush()
        stats.systems += 1
        return system

    def _get_or_create_title(
        self,
        system_id: int,
        name: str,
        description: Optional[str],
        stats: ImportStats,
    ) -> Title:
        title = self.session.execute(
            select(Title).where(Title.system_id == system_id, Title.name == name)
        ).scalar_one_or_none()
        if title:
            if description and not title.description:
                title.description = description
            return title
        title = Title(system_id=system_id, name=name, description=description)
        self.session.add(title)
        self.session.flush()
        stats.titles += 1
        return title

    def _get_or_create_release(self, title_id: int, row: Dict[str, Any], stats: ImportStats) -> Release:
        region = row.get("region")
        release_year = self._to_int(row.get("releaseyear"))
        release_month = self._to_int(row.get("releasemonth"))
        serial = row.get("serial")
        display_name = None

        release = self.session.execute(
            select(Release).where(
                Release.title_id == title_id,
                Release.region == region,
                Release.release_year == release_year,
                Release.release_month == release_month,
                Release.serial == serial,
                Release.display_name == display_name,
            )
        ).scalar_one_or_none()
        if release:
            return release

        release = Release(
            title_id=title_id,
            region=region,
            release_year=release_year,
            release_month=release_month,
            serial=serial,
            display_name=display_name,
        )
        self.session.add(release)
        self.session.flush()
        stats.releases += 1
        return release

    def _get_or_create_rom(self, release_id: int, row: Dict[str, Any], stats: ImportStats) -> Rom:
        rom_name = row.get("rom_name")
        size = self._to_int(row.get("size"))
        crc = row.get("crc")
        md5 = row.get("md5")
        sha1 = row.get("sha1")

        rom = self.session.execute(
            select(Rom).where(
                Rom.release_id == release_id,
                Rom.rom_name == rom_name,
                Rom.size == size,
                Rom.crc == crc,
                Rom.md5 == md5,
                Rom.sha1 == sha1,
            )
        ).scalar_one_or_none()
        if rom:
            return rom

        rom = Rom(
            release_id=release_id,
            rom_name=rom_name,
            size=size,
            crc=crc,
            md5=md5,
            sha1=sha1,
        )
        self.session.add(rom)
        self.session.flush()
        stats.roms += 1
        return rom

    def _store_attributes(self, release_id: int, row: Dict[str, Any], stats: ImportStats) -> None:
        for key, value in row.items():
            if not isinstance(key, str):
                stats.skipped_fields += 1
                continue
            if key in KNOWN_FIELDS:
                continue
            if value is None:
                continue
            attr = Attribute(
                entity_type="release",
                entity_id=release_id,
                key=key,
                value=str(value),
                source=self.source,
            )
            self.session.add(attr)
            stats.attributes += 1

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _merge_stats(base: ImportStats, extra: ImportStats) -> ImportStats:
        base.systems += extra.systems
        base.titles += extra.titles
        base.releases += extra.releases
        base.roms += extra.roms
        base.attributes += extra.attributes
        base.skipped_rows += extra.skipped_rows
        base.skipped_fields += extra.skipped_fields
        return base

    def _log_skipped_row(self, path: str, system_name: str, idx: int, row: Dict[str, Any]) -> None:
        if not self.skipped_log_path:
            return
        try:
            keys = [repr(key) for key in row.keys()]
            payload = (
                f"file={path} system={system_name} row={idx} keys={keys} "
                f"row={repr(row)}"
            )
            with open(self.skipped_log_path, "a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        except Exception:
            # Avoid failing the import due to logging issues.
            return
