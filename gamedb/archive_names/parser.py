"""Separate archive titles from raw naming-convention tags.

The scanner understands balanced parenthesis and square-bracket groups. A
collection profile supplies only the metadata boundary; tag interpretation is
performed separately. Offsets are zero-based and end-exclusive in the original
archive name.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import COLLECTIONS, FORMAT_VERSION, FORMATS


PARSER_VERSION = "2:" + FORMAT_VERSION.partition(":")[2]
PAIRS = {"(": ")", "[": "]"}
CLOSERS = {close: opening for opening, close in PAIRS.items()}


@dataclass(frozen=True)
class ParsedRecord:
    title_candidate: str
    tags: list[dict]
    start: int
    end: int
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedName:
    title_candidate: str
    extension: str
    tags: list[dict]
    records: tuple[ParsedRecord, ...]
    issues: tuple[str, ...]

    @property
    def status(self) -> str:
        return "review" if self.issues else "parsed"


def should_ignore_archive_name(romset: str, archive_name: str) -> bool:
    profile = FORMATS.get(romset, {})
    return any(
        archive_name.startswith(prefix)
        for prefix in profile.get("ignore_prefixes", [])
    )


def _groups(text: str, start: int = 0, end: int | None = None) -> tuple[list[dict], bool]:
    """Return top-level balanced groups and whether all delimiters balance."""
    end = len(text) if end is None else end
    stack: list[tuple[str, int]] = []
    groups = []
    balanced = True
    for position in range(start, end):
        character = text[position]
        if character in PAIRS:
            stack.append((character, position))
        elif character in CLOSERS:
            if not stack or stack[-1][0] != CLOSERS[character]:
                balanced = False
                continue
            opening, opening_position = stack.pop()
            if not stack:
                groups.append({
                    "value": text[opening_position + 1:position],
                    "delimiter": opening + character,
                    "start": opening_position,
                    "end": position + 1,
                })
    return groups, balanced and not stack


def _group_start(text: str, end: int, minimum: int) -> int | None:
    expected = []
    for position in range(end - 1, minimum - 1, -1):
        character = text[position]
        if character in CLOSERS:
            expected.append(CLOSERS[character])
        elif character in PAIRS:
            if not expected or expected.pop() != character:
                return None
            if not expected:
                return position
    return None


def _suffix_groups(text: str, start: int, end: int) -> list[dict]:
    """Recover a balanced terminal suffix even if the title is malformed."""
    groups = []
    cursor = end
    while cursor > start:
        while cursor > start and text[cursor - 1].isspace():
            cursor -= 1
        if cursor == start or text[cursor - 1] not in CLOSERS:
            break
        opening = _group_start(text, cursor, start)
        if opening is None:
            break
        groups.append({
            "value": text[opening + 1:cursor - 1],
            "delimiter": text[opening] + text[cursor - 1],
            "start": opening,
            "end": cursor,
        })
        cursor = opening
    return list(reversed(groups))


def _candidate_groups(text: str, start: int, end: int) -> tuple[list[dict], bool]:
    groups, balanced = _groups(text, start, end)
    recovered = _suffix_groups(text, start, end)
    by_position = {(group["start"], group["end"]): group for group in groups + recovered}
    return sorted(by_position.values(), key=lambda group: group["start"]), balanced


def _rule_matches(group: dict, rule: dict) -> bool:
    if rule.get("delimiter") and group["delimiter"] != rule["delimiter"]:
        return False
    regex = rule.get("regex")
    return regex is None or regex.fullmatch(group["value"]) is not None


def _boundary_index(groups: list[dict], profile: dict) -> int | None:
    boundary = profile["boundary"]
    if boundary["kind"] == "region":
        candidates = [
            index for index, group in enumerate(groups)
            if group["delimiter"] == "()"
            and all(value in boundary["values"] for value in group["value"].split(", "))
        ]
        if candidates:
            return candidates[-1]
        fallback = [
            index for index, group in enumerate(groups)
            if group["delimiter"] == "()" and group["value"] in boundary["fallback_values"]
        ]
        return fallback[-1] if fallback else None

    rules = boundary["groups"]
    candidates = []
    for index in range(len(groups) - len(rules) + 1):
        selected = groups[index:index + len(rules)]
        if all(_rule_matches(group, rule) for group, rule in zip(selected, rules)):
            gaps = [
                groups[cursor + 1]["start"] - groups[cursor]["end"]
                for cursor in range(index, index + len(rules) - 1)
            ]
            if all(gap == 0 for gap in gaps):
                candidates.append(index)
    return candidates[0] if candidates else None


def _top_level_separators(text: str, separator: str) -> list[int]:
    positions = []
    stack = []
    position = 0
    while position < len(text):
        character = text[position]
        if character in PAIRS:
            stack.append(PAIRS[character])
        elif character in CLOSERS and stack and character == stack[-1]:
            stack.pop()
        elif not stack and text.startswith(separator, position):
            positions.append(position)
            position += len(separator) - 1
        position += 1
    return positions


def _has_boundary(text: str, start: int, end: int, profile: dict) -> bool:
    groups, _ = _candidate_groups(text, start, end)
    return _boundary_index(groups, profile) is not None


def _record_ranges(stem: str, profile: dict) -> list[tuple[int, int]]:
    separator = profile.get("record_separator")
    if not separator:
        return [(0, len(stem))]
    ranges = []
    start = 0
    for position in _top_level_separators(stem, separator):
        after = position + len(separator)
        if _has_boundary(stem, start, position, profile) and _has_boundary(stem, after, len(stem), profile):
            ranges.append((start, position))
            start = after
    ranges.append((start, len(stem)))
    return ranges


def _contiguous_suffix(groups: list[dict], boundary_index: int, text: str, end: int) -> tuple[list[dict], int]:
    selected = [groups[boundary_index]]
    cursor = groups[boundary_index]["end"]
    for group in groups[boundary_index + 1:]:
        gap = text[cursor:group["start"]]
        if gap.strip(" -"):
            break
        selected.append(group)
        cursor = group["end"]
    return selected, cursor


def _prefix_tags(text: str, title_start: int, boundary_start: int, profile: dict) -> tuple[int, list[dict]]:
    title_end = boundary_start
    tags = []
    rules = profile.get("prefix_tags", [])
    # Rules are declared nearest the boundary first. Repeatedly peel a matching
    # token while retaining the source offsets and spelling.
    for rule in rules:
        prefix = text[title_start:title_end].rstrip()
        if rule.get("delimiter"):
            groups, _ = _groups(text, title_start, title_end)
            if not groups or groups[-1]["end"] != title_start + len(prefix):
                continue
            group = groups[-1]
            if _rule_matches(group, rule):
                tags.insert(0, group)
                title_end = group["start"]
        else:
            regex = rule["regex"]
            matches = list(regex.finditer(prefix))
            match = matches[-1] if matches else None
            if match and match.end() == len(prefix):
                start = title_start + match.start()
                if start > title_start and text[start - 1].isspace():
                    tags.insert(0, {
                        "value": text[start:title_start + match.end()],
                        "delimiter": "",
                        "start": start,
                        "end": title_start + match.end(),
                    })
                    title_end = start
    return title_end, tags


def _leading_tags(text: str, start: int, end: int, profile: dict) -> tuple[int, list[dict]]:
    allowed = set(profile.get("leading_tags", []))
    if not allowed:
        return start, []
    groups, _ = _groups(text, start, end)
    tags = []
    cursor = start
    for group in groups:
        if group["start"] != cursor or group["delimiter"] not in allowed:
            break
        tags.append(group)
        cursor = group["end"]
        while cursor < end and text[cursor].isspace():
            cursor += 1
    return cursor, tags


def _parse_record(text: str, start: int, end: int, profile: dict) -> ParsedRecord:
    issues = []
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    groups, balanced = _candidate_groups(text, start, end)

    boundary_index = _boundary_index(groups, profile)
    if boundary_index is None:
        title = text[start:end]
        if not balanced:
            issues.append("unbalanced_delimiters")
        issues.append("no_metadata_boundary")
        return ParsedRecord(title, [], start, end, tuple(issues))

    # Delimiter-like characters before a trustworthy metadata anchor are title
    # punctuation. Only the metadata suffix is required to balance.
    boundary_start = groups[boundary_index]["start"]
    _, suffix_balanced = _groups(text, boundary_start, end)
    if not suffix_balanced:
        issues.append("unbalanced_delimiters")

    suffix_tags, suffix_end = _contiguous_suffix(groups, boundary_index, text, end)
    if text[suffix_end:end].strip():
        issues.append("text_after_tag_suffix")

    title_start, leading = _leading_tags(text, start, groups[boundary_index]["start"], profile)
    title_end, prefix = _prefix_tags(text, title_start, groups[boundary_index]["start"], profile)
    title = text[title_start:title_end].strip()
    tags = sorted(leading + prefix + suffix_tags, key=lambda tag: tag["start"])
    if not title:
        issues.append("empty_title")
    if any(not tag["value"].strip() for tag in tags):
        issues.append("empty_tag")
    return ParsedRecord(title, tags, start, end, tuple(issues))


def parse_archive_name(romset: str, archive_name: str) -> ParsedName:
    issues = []
    extension = archive_name[-4:] if archive_name.lower().endswith(".zip") else ""
    stem = archive_name[:-4] if extension else archive_name
    if not extension:
        issues.append("missing_zip_extension")
    if romset not in FORMATS:
        issues.append("unsupported_collection")
        record = ParsedRecord(stem.strip(), [], 0, len(stem), ("unsupported_collection",))
        return ParsedName(record.title_candidate, extension, [], (record,), tuple(issues))

    profile = FORMATS[romset]
    records = tuple(
        _parse_record(stem, start, end, profile)
        for start, end in _record_ranges(stem, profile)
    )
    for record in records:
        for issue in record.issues:
            if issue not in issues:
                issues.append(issue)
    title = " & ".join(record.title_candidate for record in records)
    tags = [tag for record in records for tag in record.tags]
    return ParsedName(title, extension, tags, records, tuple(issues))
