"""Structural and semantic parsing of source archive names."""

from .structure import (
    COLLECTIONS,
    PARSER_VERSION,
    ParsedName,
    ParsedRecord,
    parse_archive_name,
    should_ignore_archive_name,
)

__all__ = [
    "COLLECTIONS",
    "PARSER_VERSION",
    "ParsedName",
    "ParsedRecord",
    "parse_archive_name",
    "should_ignore_archive_name",
]
