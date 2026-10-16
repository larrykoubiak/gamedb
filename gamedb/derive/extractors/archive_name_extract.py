"""Interpret one archive name into complete typed relational output."""

from __future__ import annotations

from gamedb.derive.parser.classifier import CLASSIFIER_VERSION, classify_tags
from gamedb.derive.parser.structure import PARSER_VERSION, parse_archive_name

from ..models import ArchiveInterpretation, InterpretedRecord
from .tag_extract import TagExtractor
from .title_extract import TitleExtractor


class ArchiveNameExtractor:
    """Orchestrate structural parsing and semantic extraction exactly once."""

    def __init__(self):
        self.tags = TagExtractor()
        self.titles = TitleExtractor()

    def extract(self, romset: str, archive_name: str) -> ArchiveInterpretation:
        parsed = parse_archive_name(romset, archive_name)
        records = []
        for index, record in enumerate(parsed.records, 1):
            parse_status = "review" if record.issues else "parsed"
            classified = classify_tags(
                romset, archive_name, record.tags, parse_status
            )
            tags, assertions, media_parts = self.tags.extract(
                record.tags, classified
            )
            records.append(InterpretedRecord(
                index=index,
                title=record.title_candidate,
                source_start=record.start,
                source_end=record.end,
                parse_status=parse_status,
                parse_issues=record.issues,
                classification_issues=classified.issues,
                tags=tags,
                assertions=assertions,
                media_parts=media_parts,
                grouping_signature=self.titles.grouping_signature(tags),
            ))
        return ArchiveInterpretation(
            romset=romset,
            archive_name=archive_name,
            extension=parsed.extension,
            parse_status=parsed.status,
            parse_issues=parsed.issues,
            parser_version=PARSER_VERSION,
            classifier_version=CLASSIFIER_VERSION,
            records=tuple(records),
        )
