"""Extract source DAT identity from staging path/name fields."""

from __future__ import annotations

import re

from sqlalchemy import bindparam, insert, text
from sqlalchemy.engine import Connection

from gamedb.arcade.schema import metadata as arcade_metadata
from ..models import SourceDat
from ..parser.config import FORMATS
from ..schema import dat_source


DAT_NAME = re.compile(
    r"(?:(Arcade) - )?(.+?) - ([^(]+)(?: \(([^)]+)\))?(?: \(([^)]+)\))?"
)


class DatExtractor:
    """Parse collection-specific DAT paths without encoding string rules in SQL."""

    version = "1"

    def extract(self, connection: Connection) -> list[SourceDat]:
        statement = text("""
            SELECT DISTINCT dat_root_full_name, dat_name
            FROM staging.rv_files
            WHERE dat_name IS NOT NULL
              AND split_part(dat_root_full_name, '/', 2) IN :collections
            ORDER BY dat_root_full_name, dat_name
        """).bindparams(bindparam("collections", expanding=True))
        rows = connection.execute(
            statement, {"collections": sorted(FORMATS)}
        )
        sources = [
            self._parse(row.dat_root_full_name, row.dat_name) for row in rows
        ]
        arcade_metadata.create_all(connection)
        arcade_rows = connection.execute(text("""
            SELECT DISTINCT rf.dat_root_full_name, rf.dat_name, src.version, split_part(src.source_key, ':', 1) AS emulator
            FROM staging.arcade_source src JOIN staging.rv_files rf
            ON rf.dat_root_full_name IN (src.rom_dat_path, src.chd_dat_path)
            ORDER BY rf.dat_root_full_name
        """))
        sources.extend(SourceDat(row.dat_root_full_name, row.dat_name, row.emulator,
                                 "Various", "Arcade", (row.version,)) for row in arcade_rows)
        integrated = connection.execute(text("""
            SELECT DISTINCT source_manufacturer, source_system
            FROM staging.integrated_package
            ORDER BY source_manufacturer, source_system
        """))
        sources.extend(SourceDat(
            dat_path=(
                f"Integrated/Undub/{row.source_manufacturer}/"
                f"{row.source_system}"
            ),
            dat_name=(
                f"{row.source_manufacturer} - {row.source_system} Undub"
            ),
            romset="Integrated",
            source_manufacturer=row.source_manufacturer,
            source_system=row.source_system,
            additional=("Undub",),
        ) for row in integrated)
        return sources

    def execute(self, connection: Connection) -> int:
        connection.execute(text("DROP SCHEMA IF EXISTS catalog CASCADE"))
        connection.execute(text(
            "TRUNCATE derived.dat_source RESTART IDENTITY CASCADE"
        ))
        sources = self.extract(connection)
        connection.execute(insert(dat_source), [
            {
                "dat_path": item.dat_path,
                "dat_name": item.dat_name,
                "romset": item.romset,
                "source_manufacturer": item.source_manufacturer,
                "source_system": item.source_system,
                "additional": list(item.additional),
            }
            for item in sources
        ])
        return len(sources)

    @staticmethod
    def _parse(dat_path: str, dat_name: str) -> SourceDat:
        parts = dat_path.split("/")[1:]
        romset = parts[0]
        strategy = FORMATS[romset]["dat_identity"]
        if strategy == "path_components":
            return SourceDat(
                dat_path, dat_name, romset, parts[1], parts[2],
                tuple(parts[3:-1]),
            )
        if strategy == "english_translations":
            source_system = re.sub(
                r"\s+\[T-En\](?:\s+\[h\])?$", "", dat_name
            )
            if source_system == dat_name:
                raise ValueError(
                    f"cannot parse English Translations DAT name: {dat_name!r}"
                )
            return SourceDat(
                dat_path, dat_name, romset, romset, source_system, ("T-En",),
            )
        if strategy != "name_components":
            raise ValueError(f"unsupported DAT identity strategy: {strategy}")
        match = DAT_NAME.fullmatch(dat_name)
        if match is None:
            raise ValueError(f"cannot parse {romset} DAT name: {dat_name!r}")
        return SourceDat(
            dat_path, dat_name, romset, match[2], match[3].rstrip(),
            tuple(value for value in (match[1], match[4], match[5]) if value),
        )
