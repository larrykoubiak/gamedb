"""Read the Saturn boot header and verify the numbered discs in a release."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import re
from zipfile import BadZipFile, ZipFile

from sqlalchemy import text

from .disc_catalog import disc_bundle
from .retail import write_report


BOOT_ID = b"SEGA SEGASATURN "
NUMBERED_DISC = re.compile(r"\(Disc\s+(\d+)\)", re.I)
BOOT_DISC = re.compile(r"CD-(\d+)/(\d+)")
MASTERING = re.compile(r"\((\d+[MS](?:,\s*\d+[MS])*)\)", re.I)
TRACK_FILES = text("""
    SELECT DISTINCT ON (package.archive_name) package.archive_name AS name,
        package.resolved_path AS path, file.member_path AS member, file.sha1_hex AS sha1,
        CASE WHEN file.crc_verified THEN file.crc_hex END AS crc,
        CASE WHEN file.size_verified THEN file.size END AS size
    FROM catalog.release_content_signature signature
    JOIN catalog.release_package part ON part.release_id = signature.release_id
    JOIN catalog.package package ON package.id = part.package_id
    JOIN catalog.package_file file ON file.package_id = package.id
    WHERE package.source_collection = 'Redump' AND package.resolved_path IS NOT NULL
      AND signature.sha1_set_digest = ANY(CAST(:signatures AS text[]))
      AND file.sha1_verified AND file.sha1_hex IS NOT NULL
      AND lower(file.member_path) LIKE '%.bin'
    ORDER BY package.archive_name, file.member_path, file.id
""")


def _boot_info(row):
    try:
        with ZipFile(row.path) as archive:
            member = archive.getinfo(row.member)
            if (row.size and row.size != member.file_size
                    or row.crc and int(row.crc, 16) != member.CRC):
                return None
            with archive.open(member) as track:
                data = track.read(16 + 256)
    except (BadZipFile, OSError, KeyError, RuntimeError, ValueError):
        return None
    for offset in (16, 0):
        if data[offset:offset + 16] == BOOT_ID:
            break
    else:
        return None
    try:
        serial, version, medium = (data[offset + start:offset + stop].decode("ascii").strip()
                                   for start, stop in ((32, 42), (42, 48), (56, 64)))
    except UnicodeDecodeError:
        return None
    record = {"serial": serial, "version": version}
    if numbering := BOOT_DISC.fullmatch(medium):
        record.update(number=int(numbering[1]), count=int(numbering[2]))
    return record


def load_headers(connection, archives, path):
    cached = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    signatures = sorted({archive["signature"] for archive in archives})
    tracks = {row.name: row for row in connection.execute(TRACK_FILES, {"signatures": signatures})}
    pending = {row.sha1: row for row in tracks.values() if row.sha1 not in cached}
    if pending:
        with ThreadPoolExecutor(max_workers=10) as workers:
            for digest, header in zip(pending, workers.map(_boot_info, pending.values()), strict=True):
                if header:
                    cached[digest] = header
        write_report(path, cached)
    return {name: cached[row.sha1] for name, row in tracks.items() if row.sha1 in cached}


def _slots(archive, headers, zero_based):
    discs = []
    for ordinal, disc in enumerate(archive["discs"], 1):
        header = headers.get(disc["name"], {})
        tag = NUMBERED_DISC.search(disc["name"])
        number = int(tag[1]) + zero_based if tag else disc.get("number") or header.get("number") or ordinal
        count = max(number, header.get("count", 1))
        discs.append((number, count, disc))
    return discs


def complete_sets(archives, headers):
    groups = defaultdict(list)
    for archive in archives:
        numbered = any(NUMBERED_DISC.search(name) for name in archive["archiveNames"])
        groups[archive["title"], tuple(archive["regions"]), numbered].append(archive)
    for group in groups.values():
        zero_based = any("(Disc 0)" in name for archive in group for name in archive["archiveNames"])
        sets = [(archive, _slots(archive, headers, zero_based)) for archive in group]
        slots = max(count for _, parts in sets for _, count, _ in parts)
        expected = set(range(1, slots + 1))
        canonical = set()
        for archive, parts in sets:
            if len(parts) == slots and {number for number, _, _ in parts} == expected:
                ordered = sorted(parts, key=lambda item: item[0])
                names = tuple(disc["name"] for _, _, disc in ordered)
                if names not in canonical:
                    yield archive if names == tuple(archive["archiveNames"]) else disc_bundle(
                        archive["title"], [(archive, disc) for _, _, disc in ordered],
                    )
                    canonical.add(names)
        if slots == 1:
            continue
        serials = defaultdict(lambda: defaultdict(dict))
        for archive, parts in sets:
            for number, _, disc in parts:
                header = headers.get(disc["name"], {})
                if header.get("serial") and (header.get("number"), header.get("count")) == (number, slots):
                    serials[header["serial"]][number].setdefault(disc["name"], (archive, disc))
        for by_number in serials.values():
            if by_number.keys() != expected:
                continue
            for entries in _complete_pressings(by_number):
                names = tuple(disc["name"] for _, disc in entries)
                if names not in canonical:
                    yield disc_bundle(group[0]["title"], entries)
                    canonical.add(names)


def _complete_pressings(discs):
    ordered = [discs[number] for number in sorted(discs)]
    if all(len(slot) == 1 for slot in ordered):
        yield [next(iter(slot.values())) for slot in ordered]
        return
    plain = [[entry for name, entry in slot.items() if not _mastering_codes(name)] for slot in ordered]
    if all(len(options) == 1 for options in plain):
        yield [options[0] for options in plain]
    codes = {code for slot in ordered if len(slot) > 1 for name in slot for code in _mastering_codes(name)}
    for code in sorted(codes):
        compatible = [[entry for name, entry in slot.items() if not (codes := _mastering_codes(name)) or code in codes]
                      for slot in ordered]
        if all(len(options) == 1 for options in compatible):
            yield [options[0] for options in compatible]


def _mastering_codes(name):
    return {code for label in MASTERING.findall(name) for code in re.split(r",\s*", label.upper())}
