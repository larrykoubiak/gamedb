"""Assemble interpreted package records into source-faithful releases."""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from itertools import groupby
from pathlib import Path
import tempfile
import time

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class Candidate:
    dat_id: int
    canonical_system_id: int
    package_id: int
    archive_name_id: int
    record_index: int
    title: str
    grouping_signature: str
    parse_status: str
    classification_issues: tuple[str, ...]
    media: tuple[dict, ...]
    ambiguous_slot: bool = False

    @property
    def single_media(self) -> dict | None:
        return self.media[0] if len(self.media) == 1 and self.media[0]["part"] else None


class ReleaseAssembler:
    """Group typed candidates in Python; SQL only persists the finished result."""

    version = "1"

    SOURCE_SQL = text("""
        SELECT
            d.id AS dat_id,
            d.canonical_system_id,
            p.id AS package_id,
            r.archive_name_id,
            r.record_index,
            r.title_text,
            r.grouping_signature,
            r.parse_status,
            r.classification_issues,
            m.source_tag_index,
            m.media_type,
            m.part,
            m.sequence,
            m.total,
            m.total_label,
            m.side,
            m.label,
            m.description
        FROM derived.package p
        JOIN derived.dat d ON d.id = p.dat_id
        JOIN derived.record r ON r.archive_name_id = p.archive_name_id
        LEFT JOIN derived.media_part m
          ON m.archive_name_id = r.archive_name_id
         AND m.record_index = r.record_index
        ORDER BY d.id, p.id, r.record_index, m.source_tag_index
    """)

    def execute(self, engine: Engine) -> dict[str, int]:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="gamedb-releases-") as directory:
            release_path = Path(directory) / "releases.csv"
            membership_path = Path(directory) / "memberships.csv"
            counts = {"source_release": 0, "source_release_package": 0}
            with (
                release_path.open("w", encoding="utf-8", newline="") as releases,
                membership_path.open("w", encoding="utf-8", newline="") as memberships,
                engine.connect() as connection,
            ):
                release_writer = csv.writer(releases, lineterminator="\n")
                membership_writer = csv.writer(memberships, lineterminator="\n")
                rows = connection.execution_options(yield_per=5000).execute(self.SOURCE_SQL)
                candidates = self._candidates(rows)
                for dat_number, (dat_id, dat_candidates) in enumerate(
                    groupby(candidates, key=lambda item: item.dat_id), 1
                ):
                    groups = self._groups(list(dat_candidates))
                    for ordinal, group in enumerate(groups, 1):
                        status, expected, available, review = self._status(group)
                        release_writer.writerow(self._csv_row((
                            dat_id, ordinal, group[0].canonical_system_id,
                            group[0].title, status, expected, available, review,
                        )))
                        counts["source_release"] += 1
                        for candidate in group:
                            media = candidate.single_media
                            membership_writer.writerow(self._csv_row((
                                dat_id, ordinal, candidate.package_id,
                                candidate.archive_name_id, candidate.record_index,
                                media["media_type"] if media else None,
                                media["part"] if media else None,
                                media["sequence"] if media else None,
                                media["total"] if media else None,
                                media["total_label"] if media else None,
                                media["side"] if media else None,
                                media["label"] if media else None,
                                media["description"] if media else None,
                            )))
                            counts["source_release_package"] += 1
                    if dat_number % 250 == 0:
                        elapsed = int(time.monotonic() - started)
                        print(
                            f"  assembled {dat_number:,} DATs, "
                            f"{counts['source_release']:,} releases ({elapsed}s)",
                            flush=True,
                        )
            with engine.begin() as connection:
                connection.execute(text("""
                    TRUNCATE derived.source_release_package,
                        derived.source_release CASCADE
                """))
                raw = connection.connection.driver_connection
                self._copy(
                    raw, release_path, "derived.source_release",
                    ("dat_id", "group_ordinal", "canonical_system_id", "title_text", "grouping_status", "expected_media_parts", "available_media_parts", "needs_review"),
                )
                self._copy(
                    raw, membership_path, "derived.source_release_package",
                    ("source_dat_id", "source_group_ordinal", "package_id", "archive_name_id", "record_index", "media_type", "media_part", "media_sequence", "media_total", "media_total_label", "media_side", "media_label", "media_description"),
                )
            return counts

    @staticmethod
    def _candidates(rows):
        key = lambda row: (
            row.dat_id, row.package_id, row.archive_name_id, row.record_index
        )
        for _, grouped in groupby(rows, key=key):
            values = list(grouped)
            first = values[0]
            media = tuple({
                "media_type": row.media_type,
                "part": row.part,
                "sequence": row.sequence,
                "total": row.total,
                "total_label": row.total_label,
                "side": row.side,
                "label": row.label,
                "description": row.description,
            } for row in values if row.source_tag_index is not None)
            yield Candidate(
                dat_id=first.dat_id,
                canonical_system_id=first.canonical_system_id,
                package_id=first.package_id,
                archive_name_id=first.archive_name_id,
                record_index=first.record_index,
                title=first.title_text,
                grouping_signature=first.grouping_signature,
                parse_status=first.parse_status,
                classification_issues=tuple(first.classification_issues),
                media=media,
            )

    def _groups(self, candidates: list[Candidate]) -> list[list[Candidate]]:
        proposed = {}
        for candidate in candidates:
            media = candidate.single_media
            if media:
                key = (
                    candidate.title, candidate.grouping_signature,
                    media["media_type"], media["total"], media["total_label"],
                )
            else:
                key = ("single", candidate.package_id, candidate.record_index)
            proposed.setdefault(key, []).append(candidate)

        groups = []
        for key, members in proposed.items():
            slots = {}
            for member in members:
                media = member.single_media
                if media:
                    slot = (media["part"], media["side"] or "")
                    slots[slot] = slots.get(slot, 0) + 1
            if any(count > 1 for count in slots.values()):
                groups.extend([
                    [replace(member, ambiguous_slot=True)] for member in members
                ])
            else:
                groups.append(members)
        return sorted(groups, key=self._group_sort_key)

    @staticmethod
    def _group_sort_key(group: list[Candidate]):
        first = group[0]
        media = first.single_media or {}
        return (
            first.title,
            first.grouping_signature,
            media.get("media_type") or "",
            media.get("total") if media.get("total") is not None else -1,
            media.get("total_label") or "",
            min(item.package_id for item in group),
            min(item.record_index for item in group),
        )

    @staticmethod
    def _status(group: list[Candidate]):
        media = [candidate.single_media for candidate in group]
        all_media = all(item is not None for item in media)
        slot_counts = {}
        for item in media:
            if item:
                slot = (item["part"], item["side"] or "")
                slot_counts[slot] = slot_counts.get(slot, 0) + 1
        ambiguous = any(item.ambiguous_slot for item in group)
        expected = min(
            (item["total"] for item in media if item and item["total"] is not None),
            default=None,
        ) if all_media else None
        parts = {item["part"] for item in media if item} if all_media else set()
        available = len(parts) if all_media else None
        numeric = [int(part) for part in parts if part.isdigit() and int(part) > 0]
        complete = (
            all_media and len(group) > 1 and expected is not None
            and len(numeric) == len(parts) == expected
            and min(numeric) == 1 and max(numeric) == expected
        )
        if ambiguous:
            status = "media_ambiguous"
        elif complete:
            status = "media_complete"
        elif all_media and len(group) > 1:
            status = "media_grouped"
        elif all_media:
            status = "media_singleton"
        else:
            status = "standalone"
        review = ambiguous or any(
            item.parse_status == "review" or item.classification_issues
            for item in group
        )
        return status, expected, available, review

    @staticmethod
    def _copy(raw_connection, path: Path, table: str, columns: tuple[str, ...]):
        statement = (
            f"COPY {table} ({', '.join(columns)}) "
            "FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
        )
        with raw_connection.cursor() as cursor, path.open("r", encoding="utf-8") as source:
            if hasattr(cursor, "copy"):
                with cursor.copy(statement) as copy:
                    while block := source.read(1024 * 1024):
                        copy.write(block)
            else:
                cursor.copy_expert(statement, source)

    @staticmethod
    def _csv_row(values):
        return tuple("\\N" if value is None else value for value in values)
