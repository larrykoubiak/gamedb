"""Bulk persistence for typed archive interpretations."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .models import ArchiveInterpretation


COPY_TARGETS = {
    "parse": (
        "derived.archive_parse",
        ("archive_name_id", "parse_status", "parse_issues", "parser_version", "classifier_version"),
    ),
    "record": (
        "derived.record",
        ("archive_name_id", "record_index", "title_text", "source_start", "source_end", "parse_status", "parse_issues", "classification_issues", "grouping_signature"),
    ),
    "tag": (
        "derived.tag",
        ("archive_name_id", "record_index", "tag_index", "raw_value", "delimiter", "source_start", "source_end"),
    ),
    "classification": (
        "derived.tag_classification",
        ("archive_name_id", "record_index", "tag_index", "identifier", "value", "category", "classification_status", "rule", "details"),
    ),
    "assertion": (
        "derived.assertion",
        ("archive_name_id", "record_index", "source_tag_index", "assertion_key", "assertion_value"),
    ),
    "media": (
        "derived.media_part",
        ("archive_name_id", "record_index", "source_tag_index", "media_type", "part", "sequence", "total", "total_label", "side", "label", "description"),
    ),
}


class InterpretationSpool:
    """Write every relational projection in one interpreter pass."""

    def __init__(self, directory: Path):
        self.paths = {name: directory / f"{name}.csv" for name in COPY_TARGETS}
        self.handles = {}
        self.writers = {}
        self.counts = {name: 0 for name in COPY_TARGETS}

    def __enter__(self):
        for name, path in self.paths.items():
            handle = path.open("w", encoding="utf-8", newline="")
            self.handles[name] = handle
            self.writers[name] = csv.writer(handle, lineterminator="\n")
        return self

    def __exit__(self, exception_type, exception, traceback):
        for handle in self.handles.values():
            handle.close()

    def write(self, archive_name_id: int, result: ArchiveInterpretation) -> None:
        self._row("parse", (
            archive_name_id, result.parse_status, self._json(result.parse_issues),
            result.parser_version, result.classifier_version,
        ))
        for record in result.records:
            self._row("record", (
                archive_name_id, record.index, record.title, record.source_start,
                record.source_end, record.parse_status,
                self._json(record.parse_issues),
                self._json(record.classification_issues),
                record.grouping_signature,
            ))
            for tag in record.tags:
                self._row("tag", (
                    archive_name_id, record.index, tag.index, tag.raw_value,
                    tag.delimiter, tag.source_start, tag.source_end,
                ))
                self._row("classification", (
                    archive_name_id, record.index, tag.index, tag.identifier,
                    tag.value, tag.category, tag.classification_status,
                    tag.rule, self._json(tag.details),
                ))
            for assertion in record.assertions:
                self._row("assertion", (
                    archive_name_id, record.index, assertion.source_tag_index,
                    assertion.key, assertion.value,
                ))
            for media in record.media_parts:
                self._row("media", (
                    archive_name_id, record.index, media.source_tag_index,
                    media.media_type, media.part, media.sequence, media.total,
                    media.total_label, media.side, media.label, media.description,
                ))

    def _row(self, name: str, values: Iterable[object]) -> None:
        self.writers[name].writerow(
            "\\N" if value is None else value for value in values
        )
        self.counts[name] += 1

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class DerivedBulkWriter:
    """COPY spooled, already-typed values without semantic SQL transforms."""

    def replace(self, connection: Connection, spool: InterpretationSpool) -> None:
        connection.execute(text("DROP SCHEMA IF EXISTS catalog CASCADE"))
        connection.execute(text("""
            TRUNCATE derived.source_release_package, derived.source_release,
                derived.media_part, derived.assertion,
                derived.tag_classification, derived.tag, derived.record,
                derived.archive_parse
            RESTART IDENTITY CASCADE
        """))
        driver_connection = connection.connection.driver_connection
        with driver_connection.cursor() as cursor:
            for name in (
                "parse", "record", "tag", "classification", "assertion", "media"
            ):
                table, columns = COPY_TARGETS[name]
                statement = (
                    f"COPY {table} ({', '.join(columns)}) "
                    "FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
                )
                with spool.paths[name].open("r", encoding="utf-8") as source:
                    with cursor.copy(statement) as copy:
                        while block := source.read(1024 * 1024):
                            copy.write(block)
