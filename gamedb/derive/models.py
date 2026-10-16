"""Typed contracts produced by archive interpretation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceDat:
    dat_path: str
    dat_name: str
    romset: str
    source_manufacturer: str
    source_system: str
    additional: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedDat:
    source: SourceDat
    system_mapping_id: int
    canonical_system_id: int


@dataclass(frozen=True)
class Assertion:
    key: str
    value: str
    source_tag_index: int


@dataclass(frozen=True)
class MediaPart:
    source_tag_index: int
    media_type: str
    part: str
    sequence: int | None = None
    total: int | None = None
    total_label: str | None = None
    side: str | None = None
    label: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class InterpretedTag:
    index: int
    raw_value: str
    delimiter: str
    source_start: int
    source_end: int
    identifier: str | None
    value: str | None
    category: str
    classification_status: str
    rule: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InterpretedRecord:
    index: int
    title: str
    source_start: int
    source_end: int
    parse_status: str
    parse_issues: tuple[str, ...]
    classification_issues: tuple[str, ...]
    tags: tuple[InterpretedTag, ...]
    assertions: tuple[Assertion, ...]
    media_parts: tuple[MediaPart, ...]
    grouping_signature: str


@dataclass(frozen=True)
class ArchiveInterpretation:
    romset: str
    archive_name: str
    extension: str
    parse_status: str
    parse_issues: tuple[str, ...]
    parser_version: str
    classifier_version: str
    records: tuple[InterpretedRecord, ...]
