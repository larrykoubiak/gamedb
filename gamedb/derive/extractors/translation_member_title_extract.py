"""Recover original titles retained in localized translation member names."""

from __future__ import annotations

from pathlib import PurePath

from sqlalchemy import insert, select, text
from sqlalchemy.engine import Connection

from ..parser.structure import PARSER_VERSION, parse_archive_name
from ..schema import translation_member_title


class TranslationMemberTitleExtractor:
    """Parse playable member names from the Maybe-Intro translation source."""

    version = "1"

    @staticmethod
    def extract(file_name: str):
        """Interpret a member basename with the archive-name grammar."""
        name = PurePath(file_name).name
        stem, separator, _extension = name.rpartition(".")
        archive_equivalent = (stem if separator else name) + ".zip"
        return parse_archive_name("English Translations", archive_equivalent)

    def execute(self, connection: Connection) -> int:
        connection.execute(text("TRUNCATE derived.translation_member_title"))
        rows = connection.execute(text("""
            SELECT file.id, file.file_name
            FROM derived.file file
            JOIN derived.package package ON package.id = file.package_id
            JOIN derived.dat dat ON dat.id = package.dat_id
            JOIN derived.archive_name archive_name
              ON archive_name.id = package.archive_name_id
            WHERE dat.romset = 'English Translations'
              AND archive_name.archive_name NOT LIKE '\\_%' ESCAPE '\\'
              AND nullif(btrim(file.file_name), '') IS NOT NULL
            ORDER BY file.id
        """)).all()

        values = []
        for file_id, file_name in rows:
            parsed = self.extract(file_name)
            record = parsed.records[0]
            issues = list(parsed.issues)
            if len(parsed.records) != 1 and "multiple_records" not in issues:
                issues.append("multiple_records")
            values.append({
                "file_id": file_id,
                "title_text": record.title_candidate,
                "parse_status": "review" if issues else "parsed",
                "parse_issues": issues,
                "parser_version": PARSER_VERSION,
            })

        if values:
            connection.execute(insert(translation_member_title), values)
        return len(values)
