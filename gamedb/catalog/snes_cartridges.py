"""Attach hardware evidence to verified cartridge content and regional releases."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
from urllib.parse import quote, urljoin
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from bs4 import BeautifulSoup
from sqlalchemy import text

from gamedb.catalog.snes_references import ARES, JENSMA, MAME, SNES_CENTRAL
from gamedb.catalog.snes_source import known_credit
from gamedb.launchbox.matching import title_key


COUNTRY_MARKETS = {
    **dict.fromkeys(("JP", "JPN", "Japan"), "JP"),
    **dict.fromkeys(("NA", "US", "USA", "CA", "CAN", "Canada", "MX", "North America"), "NA"),
    **dict.fromkeys((
        "PAL", "EU", "EUR", "EEC", "Europe", "AU", "AUS", "Australia", "NZ", "GB", "UK", "UKV",
        "United Kingdom", "DE", "GER", "NOE", "FRG", "SFRG", "Germany", "FR", "FRA", "SFRA",
        "France", "FAH", "ES", "ESP", "Spain", "IT", "ITA", "Italy", "NL", "HOL",
        "Netherlands", "SE", "SCN", "Scandinavia", "Sweden", "Denmark", "Norway", "Finland",
    ), "PAL"),
}
LIBRETRO_DB = "https://github.com/libretro/libretro-database"


def verified_roms_sql(signatures_sql):
    return f"""
    SELECT DISTINCT ON (signature.sha1_set_digest)
           signature.sha1_set_digest AS signature, package.resolved_path AS path,
           file.member_path, file.sha1_hex AS sha1,
           CASE WHEN file.crc_verified THEN lower(file.crc_hex) END AS crc32,
           CASE WHEN file.md5_verified THEN lower(file.md5_hex) END AS md5,
           CASE WHEN file.size_verified THEN file.size END AS size
    FROM catalog.release_content_signature signature
    JOIN catalog.release_package rp ON rp.release_id = signature.release_id
    JOIN catalog.package package ON package.id = rp.package_id
    JOIN catalog.package_file file ON file.package_id = package.id
    WHERE signature.sha1_set_digest = ANY({signatures_sql})
      AND signature.package_count = 1 AND signature.rom_count = 1
      AND package.source_collection = 'No-Intro' AND package.resolved_path IS NOT NULL
      AND file.sha1_verified AND file.sha1_hex IS NOT NULL
    ORDER BY signature.sha1_set_digest, package.archive_name, file.id
"""


VERIFIED_ROM_SQL = text(verified_roms_sql("CAST(:signatures AS text[])"))

RDB_SQL = text("""
    WITH latest AS (
        SELECT id, source_revision FROM staging.libretro_rdb_import
        ORDER BY imported_at DESC, id DESC LIMIT 1
    )
    SELECT DISTINCT entry.sha1_hex AS sha1, entry.serial, entry.name, latest.source_revision,
           entry.raw_record->>'developer' AS developer
    FROM latest
    JOIN staging.libretro_rdb_file file ON file.import_id = latest.id
    JOIN staging.libretro_rdb_entry entry ON entry.file_id = file.id
    WHERE entry.sha1_hex = ANY(CAST(:hashes AS text[]))
      AND file.database_name IN ('Nintendo - Super Nintendo Entertainment System', 'Nintendo - Sufami Turbo')
    ORDER BY entry.sha1_hex, entry.serial, entry.name
""")


def read_cartridge_roms(connection, catalog):
    signatures = sorted({archive["signature"] for game in catalog["games"] for release in game["releases"]
                         for archive in release.get("archives", ())})
    return {row.signature: row for row in connection.execute(VERIFIED_ROM_SQL, {"signatures": signatures})}


def _fingerprint(rom):
    path = Path(rom.path)
    if path.suffix.lower() != ".zip":
        return None
    try:
        with ZipFile(path) as archive, archive.open(rom.member_path) as stream:
            content = stream.read(16 * 1024 * 1024 + 1)
    except (OSError, BadZipFile, KeyError, RuntimeError):
        return None
    if len(content) > 16 * 1024 * 1024 or sha1(content).hexdigest() != rom.sha1:
        return None
    return sha256(content).hexdigest()


def cartridge_hashes(path, roms, refresh=False):
    cached = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if refresh:
        pending = {rom.sha1: rom for rom in roms.values() if rom.sha1 not in cached}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for digest, fingerprint in zip(pending, pool.map(_fingerprint, pending.values()), strict=True):
                if fingerprint:
                    cached[digest] = fingerprint
    return cached


def _markets_in_label(label):
    return {COUNTRY_MARKETS[region.strip()] for group in re.findall(r"\(([^()]*)\)", label or "")
            for region in group.split(",") if region.strip() in COUNTRY_MARKETS}


def _serials(value):
    value = re.sub(r"\s+\([A-Z0-9-]+\)", "", value or "")
    return sorted({part.strip() for part in re.split(r"[,/]\s*", value or "")
                   if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)+|[A-Z][A-Z0-9]{3}", part.strip())})


def _markets_in_serial(value):
    prefix, *parts = value.split("-")
    if len(parts) > 1 and (suffix := parts[-1]) in COUNTRY_MARKETS:
        return COUNTRY_MARKETS[suffix]
    return {"SNS": "NA", "SHVC": "JP", "SFT": "JP", "SNSP": "PAL",
            "SPAL": "PAL", "SFRG": "PAL", "SFRA": "PAL"}.get(prefix)


def serial_core(value):
    match = re.fullmatch(r"(?:M/)?(?:SNSP?|SHVC|SPAL|SFRG|SFRA|SFT)-([A-Z0-9]{2,4})(?:-.+)?", value)
    return match[1] if match else value if re.fullmatch(r"[A-Z0-9]{4}", value) else None


def mame_cartridges(content, filename):
    for item in ElementTree.fromstring(content).findall("software"):
        label = item.findtext("description", "")
        if re.search(r"\b(?:prototype|bootleg|pirate|unl|beta|sample|demo)\b", label, flags=re.I):
            continue
        info = {node.get("name"): node.get("value") for node in item.findall("info")}
        for part in item.findall("part"):
            # The program area can share a cartridge with separate DSP firmware.
            # A board with several program chips cannot be linked by one chip hash.
            roms = part.findall("dataarea[@name='rom']/rom")
            if len(roms) != 1 or not roms[0].get("sha1"):
                continue
            pcb = part.find("feature[@name='pcb']")
            models = pcb.get("value", "") if pcb is not None else info.get("pcb", "")
            boards = [model.strip() for model in models.split(",") if re.fullmatch(r"[A-Z0-9-]+", model.strip())]
            serials = _serials(info.get("serial"))
            markets = _markets_in_label(label) or {_markets_in_serial(code) for code in serials} - {None}
            yield roms[0].get("sha1"), markets, {
                "serials": serials, "boards": boards, "publisher": item.findtext("publisher"),
                "developer": info.get("developer"), "date": info.get("release"),
                "source": {"name": "MAME", "url": MAME + filename, "record": item.get("name")},
            }


def ares_cartridges(content):
    for block in re.split(r"(?m)^game\s*$", content.decode("utf-8"))[1:]:
        fields = dict(re.findall(r"(?m)^  (sha256|region|board):[ \t]*(.+?)\s*$", block))
        if "sha256" not in fields or "board" not in fields:
            continue
        serials = _serials(fields.get("region"))
        markets = {COUNTRY_MARKETS.get(fields.get("region")), *map(_markets_in_serial, serials)} - {None}
        yield fields["sha256"], markets, {
            "serials": serials, "boards": [fields["board"]],
            "source": {"name": "ares", "url": ARES, "record": fields["sha256"]},
        }


def _central_rows(region_or_board, html):
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr", recursive=False)
        if not rows:
            continue
        header = [cell.get_text(" ", strip=True).casefold() for cell in rows[0].find_all(["th", "td"], recursive=False)]
        labels = header == ["game name", "serial code", "notes", "link"]
        boards = header == ["game name", "region", "serial code"]
        if not (labels or boards):
            continue
        for row in rows[1:]:
            cells = row.find_all("td", recursive=False)
            if len(cells) != len(header):
                continue
            name, second, third, *_ = [cell.get_text(" ", strip=True) for cell in cells]
            region, serial = (region_or_board, second) if labels else (second, third)
            if not name or not serial_core(serial) or region not in COUNTRY_MARKETS:
                continue
            if labels and re.search(r"prototype|not for resale|bootleg|sample|competition", third, re.I):
                continue
            link = row.find("a", href=re.compile(r"^(?:cart|article)\.php\?id=\d+"))
            if link:
                yield name, COUNTRY_MARKETS[region], serial, {
                    "serials": [serial] if labels else [], "boards": [region_or_board] if boards else [],
                    "romChip": serial if boards else None, "region": region,
                    "source": {"name": "SNES Central", "url": urljoin(SNES_CENTRAL, link["href"])},
                }


def _jensma_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 5:
            continue
        name, identity, _, _, pcb = [cell.get_text(" ", strip=True) for cell in cells]
        if re.search(r"\b(?:prototype|sample|bootleg|demo)\b", name, re.I):
            continue
        codes = _serials(re.sub(r"\s+\([A-Z]{2,4}\)", "", identity))
        markets = {_markets_in_serial(code) for code in codes}
        if len(markets) != 1 or None in markets:
            continue
        (market,) = markets
        for code in codes:
            if not serial_core(code) or serial_core(code) in {"7777", "XXXX"}:
                continue
            board = pcb if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+){1,4}", pcb) else None
            yield name, market, code, {
                "serials": [code], "boards": [board] if board else [],
                "source": {"name": "Jensma SNES Database", "url": f"{JENSMA}?id={quote(identity, safe='')}"},
            }


def add_cartridge_evidence(connection, catalog, roms, fingerprints, indexes, central, reference):
    checked = defaultdict(list)
    for name, filename in (("mame.xml", "snes.xml"), ("mame-strom.xml", "snes_strom.xml")):
        if name in indexes:
            for digest, markets, record in mame_cartridges(indexes[name].content, filename):
                checked[digest].append((markets, record))
    if "ares-snes.bml" in indexes:
        verified = defaultdict(list)
        for digest, markets, record in ares_cartridges(indexes["ares-snes.bml"].content):
            verified[digest].append((markets, record))
        for digest, fingerprint in fingerprints.items():
            checked[digest].extend(verified.get(fingerprint, ()))
    present = connection.execute(text("""
        SELECT to_regclass('staging.libretro_rdb_entry') IS NOT NULL
           AND to_regclass('staging.libretro_rdb_file') IS NOT NULL
           AND to_regclass('staging.libretro_rdb_import') IS NOT NULL
    """)).scalar_one()
    if present:
        for row in connection.execute(RDB_SQL, {"hashes": sorted({rom.sha1 for rom in roms.values()})}):
            serials = _serials(row.serial)
            developer = row.developer if known_credit(row.developer) else None
            if serials or developer:
                markets = {_markets_in_serial(code) for code in serials} - {None}
                checked[row.sha1].append((markets or _markets_in_label(row.name), {
                    "serials": serials, "boards": [], "developer": developer,
                    "source": {"name": "Libretro", "url": LIBRETRO_DB, "revision": row.source_revision},
                }))

    releases = {release["key"]: release for game in catalog["games"] for release in game["releases"]}
    by_name, by_code = defaultdict(set), defaultdict(set)
    for key, release in releases.items():
        codes = set()
        for archive in release.get("archives", ()):
            rom = roms.get(archive["signature"])
            if not rom:
                continue
            records = []
            for markets, record in checked.get(rom.sha1, ()):
                if markets and release["market"] not in markets:
                    continue
                record = {**record, "serials": [code for code in record["serials"]
                          if _markets_in_serial(code) in (None, release["market"])]}
                if release["channel"] == "sufami-turbo":
                    record["serials"] = [code for code in record["serials"] if code.startswith("SFT-")]
                codes.update(core for code in record["serials"] if (core := serial_core(code)))
                if any(record.get(field) for field in ("serials", "boards", "publisher", "developer", "date")):
                    if record not in records:
                        records.append(record)
            if records:
                archive["cartridge"] = records
        for field in ("publisher", "developer"):
            credits = {record[field]: record["source"] for archive in release.get("archives", ())
                       for record in archive.get("cartridge", ()) if known_credit(record.get(field))}
            if len(credits) == 1:
                value, source = next(iter(credits.items()))
                release[field] = value
                release.setdefault("creditSources", {})[field] = source
        if release["status"] != "matched" or release["channel"] != "cartridge":
            continue
        for code in codes:
            by_code[release["market"], code].add(key)
        for title in {*release["titles"], *(archive["title"] for archive in release.get("archives", ()))}:
            by_name[release["market"], title_key(title)].add(key)
    by_edition = {(release["edition"], release["market"]): release["key"] for release in releases.values()
                  if release["status"] == "matched" and release["channel"] == "cartridge"}
    for alias in reference.get("cartridgeAliases", ()):
        if key := by_edition.get((alias["edition"], alias["market"])):
            by_name[alias["market"], title_key(alias["title"])].add(key)

    sources = [_central_rows(region, index.content) for region, index in central]
    if "jensma-index.html" in indexes:
        sources.append(_jensma_rows(indexes["jensma-index.html"].content))
    for records in sources:
        for name, market, serial, record in records:
            titles = by_name[market, title_key(name)]
            codes = by_code[market, serial_core(serial)]
            candidates = titles & codes if titles and codes else titles or codes
            if len(candidates) == 1:
                (key,) = candidates
                notes = releases[key].setdefault("cartridgeScans", [])
                if record not in notes:
                    notes.append(record)
    for item in reference.get("cartridges", ()):
        if key := by_edition.get((item["edition"], item["market"])):
            release = releases[key]
            if item.get("sha1") and not any(
                archive["signature"] in roms and roms[archive["signature"]].sha1 == item["sha1"]
                for archive in release.get("archives", ())
            ):
                continue
            record = {field: value for field, value in item.items() if field not in {"edition", "market"}}
            release.setdefault("cartridgeScans", []).append(record)
