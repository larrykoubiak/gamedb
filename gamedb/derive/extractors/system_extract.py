"""Resolve parsed source systems through maintained mappings."""

from __future__ import annotations

from sqlalchemy import insert, select, text
from sqlalchemy.engine import Connection

from ..models import ResolvedDat, SourceDat
from ..schema import dat, dat_source, system_mapping


class SystemExtractor:
    """Give each source DAT one reviewed canonical-system identity."""

    version = "1"

    def resolve(
        self, connection: Connection, source_dats: list[tuple[int, SourceDat]]
    ) -> list[tuple[int, ResolvedDat]]:
        mappings = {
            (row.romset, row.source_manufacturer, row.source_system): (
                row.id, row.canonical_system_id
            )
            for row in connection.execute(select(system_mapping))
        }
        missing = []
        resolved = []
        for source_id, source in source_dats:
            key = (source.romset, source.source_manufacturer, source.source_system)
            if key not in mappings:
                missing.append(key)
                continue
            mapping_id, canonical_id = mappings[key]
            resolved.append((source_id, ResolvedDat(source, mapping_id, canonical_id)))
        if missing:
            examples = ", ".join(map(str, missing[:5]))
            raise ValueError(
                f"{len(missing)} DAT rows lack system mappings; examples: {examples}"
            )
        return resolved

    @staticmethod
    def load(connection: Connection, resolved: list[tuple[int, ResolvedDat]]) -> None:
        connection.execute(insert(dat), [
            {
                "dat_source_id": source_id,
                "dat_path": item.source.dat_path,
                "dat_name": item.source.dat_name,
                "romset": item.source.romset,
                "source_manufacturer": item.source.source_manufacturer,
                "source_system": item.source.source_system,
                "additional": list(item.source.additional),
                "system_mapping_id": item.system_mapping_id,
                "canonical_system_id": item.canonical_system_id,
            }
            for source_id, item in resolved
        ])

    def execute(self, connection: Connection) -> int:
        connection.execute(text("DROP SCHEMA IF EXISTS catalog CASCADE"))
        connection.execute(text("TRUNCATE derived.dat RESTART IDENTITY CASCADE"))
        sources = [
            (
                row.id,
                SourceDat(
                    row.dat_path, row.dat_name, row.romset,
                    row.source_manufacturer, row.source_system,
                    tuple(row.additional),
                ),
            )
            for row in connection.execute(select(dat_source))
        ]
        resolved = self.resolve(connection, sources)
        self.load(connection, resolved)
        return len(resolved)
