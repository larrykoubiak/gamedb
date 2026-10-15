"""Parse archive names for the loader independently of their source."""

from .parser import (
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
