"""Load maintained reference inputs used by all extractors."""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import insert, select, text
from sqlalchemy.engine import Connection

from ..schema import (
    canonical_system, path_mapping, software_correction, system_mapping,
    tag_category,
)


class ReferenceExtractor:
    """Load reviewed CSV references and expose their stable source-text keys."""

    def __init__(self, reference_directory: Path):
        self.reference_directory = reference_directory

    def execute(self, connection: Connection) -> None:
        connection.execute(text("""
            TRUNCATE ref.software_correction, ref.tag_category, ref.path_mapping,
                ref.system_mapping, ref.canonical_system
            RESTART IDENTITY CASCADE
        """))
        systems = self._rows("canonical_systems.csv")
        connection.execute(insert(canonical_system), [
            {
                "manufacturer_name": row["canonical_manufacturer_name"],
                "system_name": row["canonical_system_name"],
            }
            for row in systems
        ])
        system_ids = {
            (row.manufacturer_name, row.system_name): row.id
            for row in connection.execute(select(canonical_system))
        }

        mappings = self._rows("system_mappings.csv")
        connection.execute(insert(system_mapping), [
            {
                "romset": row["romset"],
                "source_manufacturer": row["source_manufacturer"],
                "source_system": row["source_system"],
                "canonical_system_id": system_ids[(
                    row["canonical_manufacturer"], row["canonical_system"]
                )],
                "match_method": row["match_method"],
                "notes": row["notes"] or None,
            }
            for row in mappings
        ])
        connection.execute(insert(path_mapping), self._rows("path_mappings.csv"))
        connection.execute(insert(tag_category), self._rows("tag_categories.csv"))
        corrections = self._rows("software_corrections.csv")
        if corrections:
            connection.execute(insert(software_correction), [
                {
                    **row,
                    "target_content_signature":
                        row["target_content_signature"] or None,
                }
                for row in corrections
            ])

    def _rows(self, name: str) -> list[dict[str, str]]:
        path = self.reference_directory / name
        # Some maintained CSVs originate from spreadsheet tools and retain a
        # UTF-8 BOM. utf-8-sig accepts both BOM and ordinary UTF-8 inputs.
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
