"""Extract candidate titles and unqualified tags from archive names.

Offsets are zero-based, end-exclusive Python character offsets in archive_name.
Tags retain their spelling, order, duplicates and delimiters. No tag vocabulary
or canonical-title matching is applied here.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


PARSER_VERSION = "1"
COLLECTIONS = frozenset({"No-Intro", "Redump", "TOSEC", "TOSEC-ISO"})
TOSEC_COLLECTIONS = frozenset({"TOSEC", "TOSEC-ISO"})
PAIRS = {"(": ")", "[": "]"}
OPENERS = {close: opening for opening, close in PAIRS.items()}
# TOSEC permits an unbracketed version immediately after the title. Extract
# only these bounded forms; retain the original token as an unqualified tag.
BARE_SUFFIX = re.compile(
    r"\s+(?:v\d[\w.+-]*|rev(?:ision)?\.?\s+[A-Za-z0-9][\w.+-]*)$",
    re.IGNORECASE,
)
# A TOSEC date followed immediately by a publisher group anchors its metadata
# suffix. This is a boundary rule only; both values remain unqualified tags.
TOSEC_BOUNDARY = re.compile(r"\([0-9xX]{4}(?:-[0-9xX]{2}){0,2}\)(?=\()")
DEMO_SUFFIX = re.compile(r"\s+\(demo(?:-[^()]*)?\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedName:
    title_candidate: str
    extension: str
    tags: list[dict]
    issues: tuple[str, ...]

    @property
    def status(self) -> str:
        return "review" if self.issues else "parsed"


def _group_start(text: str, end: int) -> int | None:
    """Find the matching opening delimiter, including nested groups."""
    expected = []
    for pos in range(end - 1, -1, -1):
        char = text[pos]
        if char in OPENERS:
            expected.append(OPENERS[char])
        elif char in PAIRS:
            if not expected or expected.pop() != char:
                return None
            if not expected:
                return pos
    return None


def _balanced(text: str) -> bool:
    expected = []
    for char in text:
        if char in PAIRS:
            expected.append(PAIRS[char])
        elif char in OPENERS:
            if not expected or expected.pop() != char:
                return False
    return not expected


def parse_archive_name(romset: str, archive_name: str) -> ParsedName:
    issues = []
    if romset not in COLLECTIONS:
        issues.append("unsupported_collection")

    extension = archive_name[-4:] if archive_name.lower().endswith(".zip") else ""
    stem = archive_name[:-4] if extension else archive_name
    if not extension:
        issues.append("missing_zip_extension")

    # Work backwards through the contiguous suffix of groups. Parentheses
    # embedded within title text stay in the title and are marked for review.
    end = len(stem.rstrip())
    boundary = TOSEC_BOUNDARY.search(stem) if romset in TOSEC_COLLECTIONS else None
    minimum = boundary.start() if boundary else 0
    if boundary:
        demo = DEMO_SUFFIX.search(stem[:minimum])
        if demo:
            minimum = stem.index("(", demo.start())
    reversed_tags = []
    while end and stem[end - 1] in OPENERS:
        start = _group_start(stem, end)
        if start is None:
            issues.append("unbalanced_delimiters")
            break
        if start < minimum:
            break
        reversed_tags.append({
            "value": stem[start + 1:end - 1],
            "delimiter": stem[start] + stem[end - 1],
            "start": start,
            "end": end,
        })
        end = len(stem[:start].rstrip())

    tags = list(reversed(reversed_tags))
    if not tags:
        issues.append("no_tag_suffix")

    prefix = stem[:end]
    if romset in TOSEC_COLLECTIONS and tags:
        match = BARE_SUFFIX.search(prefix)
        if match:
            start = match.start()
            while start < end and prefix[start].isspace():
                start += 1
            tags.insert(0, {
                "value": prefix[start:end], "delimiter": "",
                "start": start, "end": end,
            })
            prefix = prefix[:match.start()]

    # Leading square-bracket groups are also syntactic tags (e.g. [BIOS]).
    # Keep their original positions; tag order always follows the source name.
    prefix_start = 0
    while prefix[prefix_start:].lstrip().startswith("["):
        start = prefix_start + len(prefix[prefix_start:]) - len(prefix[prefix_start:].lstrip())
        expected = []
        stop = None
        for pos in range(start, len(prefix)):
            char = prefix[pos]
            if char in PAIRS:
                expected.append(PAIRS[char])
            elif char in OPENERS:
                if not expected or expected.pop() != char:
                    break
                if not expected:
                    stop = pos + 1
                    break
        if stop is None or (stop < len(prefix) and not prefix[stop].isspace()):
            break
        tags.append({"value": prefix[start + 1:stop - 1], "delimiter": "[]", "start": start, "end": stop})
        prefix_start = stop
    prefix = prefix[prefix_start:]
    tags.sort(key=lambda tag: tag["start"])

    title = prefix.strip()
    if not title:
        issues.append("empty_title")
    if not _balanced(stem) and "unbalanced_delimiters" not in issues:
        issues.append("unbalanced_delimiters")
    if any(char in prefix for char in "()[]"):
        issues.append("groups_or_text_remaining_in_title")
    if stem.startswith("ZZZ-UNK-"):
        issues.append("legacy_unknown_name")
    if any(not tag["value"].strip() for tag in tags):
        issues.append("empty_tag")

    return ParsedName(title, extension, tags, tuple(issues))
