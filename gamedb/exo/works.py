"""Reconcile eXo source records while retaining their original playable editions."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from urllib.parse import unquote, urlsplit


def name_key(name):
    name = name.casefold().strip()
    if name.endswith(", the"):
        name = "the " + name[:-5]
    return " ".join(re.findall(r"\w+", name))


def publisher_key(value):
    return re.sub(
        r"(?: (?:incorporated|inc|corporation|corp|limited|ltd|llc|gmbh))+$",
        "",
        name_key(value),
    )


def credit(value):
    normalized = publisher_key(value)
    return (
        ""
        if normalized
        in {
            "unknown",
            "various",
            "freeware",
            "shareware",
            "public domain",
            "n a",
            "self published",
        }
        else normalized
    )


def title_key(value):
    normalized = name_key(re.sub(r"\]\s*\[", " II ", value)).removeprefix("the ")
    return " ".join(ROMAN_NUMBERS.get(word, word) for word in normalized.split())


ROMAN_NUMBERS = dict(
    zip(
        ["ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"],
        map(str, range(2, 13)),
    )
)
EDITION_MARKERS = re.compile(
    r"\b(?:\d+|i{1,3}|iv|v|vi{1,3}|ix|x|remake|remaster(?:ed)?|deluxe|enhanced|"
    r"anniversary|compilation|collection|anthology|expansion|demo|trainer)\b"
)
VARIANT = re.compile(
    r"\b(?:remake|remaster(?:ed)?|enhanced|restored|mod|demo|patch|making of)\b",
    re.IGNORECASE,
)
SOURCE_PRIORITY = {"MS-DOS": 0, "Windows 9x": 1, "ScummVM": 2}


def article_path(value):
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    prefix = "/wiki/"
    if (
        parts.hostname == "en.wikipedia.org"
        and parts.path.startswith(prefix)
        and not parts.fragment
    ):
        return unquote(parts.path[len(prefix) :]).replace("_", " ").casefold()
    return ""


@dataclass(frozen=True)
class Record:
    work: str
    source: str
    title: str
    aliases: frozenset[str]
    developer: str
    publisher: str
    released: date | None
    database_id: str
    notes: str
    release_type: str
    article: str

    @classmethod
    def from_entry(cls, entry, work):
        fields = entry["fields"]
        try:
            released = date.fromisoformat(fields.get("ReleaseDate", "")[:10])
        except ValueError:
            released = None
        title = title_key(entry["title"])
        aliases = frozenset(
            title_key(a["Name"]) for a in entry["aliases"] if a.get("Name")
        )
        notes = " ".join(fields.get("Notes", "").casefold().split())
        return cls(
            work,
            entry["source_list"],
            title,
            aliases,
            credit(fields.get("Developer", "")),
            credit(fields.get("Publisher", "")),
            released,
            fields.get("DatabaseID", ""),
            notes,
            (fields.get("ReleaseType") or "Released").casefold(),
            article_path(fields.get("WikipediaURL", "")),
        )


def match_basis(a, b):
    if a.source == b.source or a.work == b.work:
        return None
    if a.release_type != b.release_type:
        return None
    same_title = a.title == b.title
    if not same_title:
        if a.title not in b.aliases and b.title not in a.aliases:
            return None
        if EDITION_MARKERS.findall(a.title) != EDITION_MARKERS.findall(b.title):
            return None
    developer = bool(a.developer and a.developer == b.developer)
    publisher = bool(a.publisher and a.publisher == b.publisher)
    shared_id = bool(a.database_id and a.database_id == b.database_id)
    notes = len(a.notes) >= 100 and a.notes == b.notes
    if notes and (developer or publisher or shared_id):
        return "source description and credits or database ID"
    if not a.released or not b.released:
        return None
    years = abs(a.released.year - b.released.year)
    same_day = abs((a.released - b.released).days) <= 1
    if (
        same_title
        and a.article
        and a.article == b.article
        and years <= 3
        and (developer or publisher)
    ):
        return "source article, credits and release dates"
    if shared_id and years <= 2 and (developer or publisher):
        return "database ID, credits and release dates"
    if developer and publisher and years <= 1:
        return "developer, publisher and release dates"
    if same_title and developer and (years == 0 or same_day):
        return "developer and release year or adjacent dates"
    known_day = all((d.month, d.day) != (1, 1) for d in (a.released, b.released))
    if same_title and same_day and notes:
        return "source description and release date"
    if same_title and same_day and publisher and known_day:
        return "publisher and precise release date"
    return None


def read_reviewed_matches(path):
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    members = {row["alias_key"] for row in rows}
    if len(members) != len(rows) or any(row["work_key"] in members for row in rows):
        raise ValueError(
            "Reviewed eXo work matches must point directly to a single canonical work"
        )
    return rows


def source_work_aliases(entries, editions, reviewed=()):
    """Return old work keys and their canonical keys, including evidence for each merge."""
    existing = {e["work_key"] for e in editions}
    verified = {
        r["alias_key"]: r
        for r in reviewed
        if {r["alias_key"], r["work_key"]} <= existing
    }
    targets = {alias: row["work_key"] for alias, row in verified.items()}
    works_by_entry = defaultdict(lambda: defaultdict(list))
    sources = defaultdict(set)
    priorities = {}
    entry_by_key = {g["entry_key"]: g for g in entries}
    for edition in editions:
        entry = entry_by_key[edition["entry_key"]]
        work = targets.get(edition["work_key"], edition["work_key"])
        source = entry["source_list"]
        works_by_entry[edition["entry_key"]][work].append(edition)
        sources[work].add(source)
        priority = (SOURCE_PRIORITY.get(source, len(SOURCE_PRIORITY)), work)
        priorities[work] = min(priorities.get(work, priority), priority)

    # A bundle can contain sequels, remakes and bonuses. Only an unambiguous original
    # matching the parent title can inherit the parent XML metadata.
    by_name = defaultdict(list)
    for entry in entries:
        works = works_by_entry[entry["entry_key"]]
        if len(works) > 1:
            title = title_key(entry["title"])
            works = {
                work
                for work, choices in works.items()
                if any(title_key(choice["work_title"]) == title for choice in choices)
                and not any(
                    choice["is_mod"] or VARIANT.search(choice["label"])
                    for choice in choices
                )
            }
        if len(works) != 1:
            continue
        record = Record.from_entry(entry, next(iter(works)))
        for name in sorted({record.title, *record.aliases} - {""}):
            by_name[name].append(record)

    neighbors = defaultdict(dict)
    for candidates in by_name.values():
        for a, b in combinations(candidates, 2):
            basis = match_basis(a, b)
            if basis:
                prefix = "title" if a.title == b.title else "documented alternate title"
                reason = f"{prefix}, {basis}"
                current = neighbors[a.work].get(b.work, reason)
                neighbors[a.work][b.work] = neighbors[b.work][a.work] = min(
                    current, reason
                )

    aliases = []
    pending = set(neighbors)
    while pending:
        component = set()
        queue = [pending.pop()]
        while queue:
            work = queue.pop()
            component.add(work)
            unseen = neighbors[work].keys() & pending
            pending.difference_update(unseen)
            queue.extend(unseen)
        # A third record cannot bridge two different games. Every pair needs its own
        # evidence, and a group cannot absorb two independent works from the same list.
        if any(
            b not in neighbors[a] or sources[a] & sources[b]
            for a, b in combinations(component, 2)
        ):
            continue
        target = min(component, key=priorities.__getitem__)
        for alias in sorted(component - {target}):
            aliases.append(
                {
                    "alias_key": alias,
                    "work_key": target,
                    "match_basis": neighbors[alias][target],
                }
            )
    automatic = {row["alias_key"]: row["work_key"] for row in aliases}
    for alias, row in verified.items():
        aliases.append(
            {
                "alias_key": alias,
                "work_key": automatic.get(row["work_key"], row["work_key"]),
                "match_basis": row["match_basis"],
            }
        )
    return sorted(aliases, key=lambda row: row["alias_key"])
