"""Build the curated Mega Drive cartridge catalog."""

from collections import defaultdict
from dataclasses import dataclass
import json
import re
from xml.etree import ElementTree

from gamedb.catalog import retail
from gamedb.catalog.megadrive_media import DIGITAL_PRESS, add_scans, sega_retro_scans
from gamedb.catalog.megadrive_source import HTML_URL, parse_retail_list
from gamedb.catalog.cartridges import COUNTRY_MARKETS, LIBRETRO_DB, VERIFIED_ROM_SQL, rdb_cartridge_records
from gamedb.catalog.retail_media import add_descriptions_and_art
from gamedb.catalog.references import MAME, MAME_RAW, read_index
from gamedb.catalog.soundtracks import add_soundtracks
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine


SYSTEM = ("Sega", "Mega Drive")
ARCHIVE_MARKETS = retail.ARCHIVE_MARKETS | {"BR": {"BR"}, "KR": {"KR"}, "AS": {"AS", "HK"}}
SCAN_MARKETS = COUNTRY_MARKETS | {region: market for market, regions in ARCHIVE_MARKETS.items()
                                for region in regions} | {
    "Brazil": "BR", "Korea": "KR", "Asia": "AS", "Euro": "PAL", "Hong Kong": "AS",
}
THUMBNAILS = {"megadrive": ("Sega - Mega Drive - Genesis", "b81fd421cc18d95a1d3df2c500267e7917ae09a1")}
REFERENCE = PROJECT_ROOT / "reference/megadrive_retail.json"
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/megadrive-retail"
MAME_FILE = "megadriv.xml"
EXCLUDED_MAME = re.compile(
    r"\([^()]*\b(?:prototype|proto|bootleg|pirate|unl|beta|sample|demo|hack|sega channel|meganet)\b", re.I,
)


@dataclass(frozen=True)
class Cartridge:
    digest: str
    group: str
    names: tuple
    markets: frozenset
    evidence: dict


def cartridge_records(xml):
    for software in ElementTree.fromstring(xml).findall("software"):
        label = software.findtext("description", "")
        if EXCLUDED_MAME.search(label):
            continue
        names, markets = [], set()
        for local in label.split(" ~ "):
            if match := re.search(r"\s*\(([^()]*)\)$", local):
                territories = {SCAN_MARKETS[region.strip()] for region in match[1].split(",")
                               if region.strip() in SCAN_MARKETS}
                if territories or "World" in match[1]:
                    markets.update(territories)
                    local = local[:match.start()]
            names.append(local)

        info = {node.get("name"): node.get("value") for node in software.findall("info")}
        for part in software.findall("part"):
            program = part.findall("dataarea[@name='rom']/rom")
            if len(program) != 1 or not (digest := program[0].get("sha1")):
                continue
            boards = [model for pcb in part.findall("feature[@name='pcb']")
                      if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+){1,5}", model := pcb.get("value", ""))]
            serials = [{
                "code": match[1], "market": SCAN_MARKETS.get(match[2]) if match[2] else None,
            } for serial in (info.get("serial") or "").split(",")
                if (match := re.fullmatch(r"\s*([A-Za-z0-9-]+)(?:\s*\(([^()]+)\))?\s*", serial))]
            detail = {
                "source": {"name": "MAME", "url": MAME + MAME_FILE, "record": software.get("name")},
                "boards": boards, "productCodes": serials,
            }
            slot = part.find("feature[@name='slot']")
            if ("J-Cart" in label or
                    slot is not None and slot.get("value") in {"rom_jcart", "rom_jcart_sampras"}):
                detail["peripherals"] = ["j-cart"]
            yield Cartridge(digest, software.get("cloneof", software.get("name")), tuple(names),
                            frozenset(markets), detail)


def mame_matches(catalog, archives, roms, records):
    return retail.cartridge_group_matches(catalog, archives, roms, records, markets=ARCHIVE_MARKETS)


def add_cartridge_details(catalog, roms, records, rdb=()):
    by_digest, headers = defaultdict(list), defaultdict(dict)
    for record in records:
        by_digest[record.digest].append(record)
    for row in rdb:
        serial = (row.serial or "").strip()
        if re.fullmatch(r"[A-Z0-9-]{2,24}(?:\.\d+)?", serial) and re.search(r"[1-9]", serial):
            headers[row.sha1][serial] = row.source_revision
    coverage = dict.fromkeys(ARCHIVE_MARKETS, 0)
    for game in catalog["games"]:
        for release in game["releases"]:
            market = release["market"]
            has_header = False
            for archive in release.get("archives", ()):
                digest = roms.get(archive["signature"])
                for record in by_digest[digest]:
                    info = record.evidence
                    codes = [entry["code"] for entry in info["productCodes"]
                             if entry["market"] == market or (entry["market"] is None and record.markets == {market})]
                    detail = {"source": info["source"], "serials": codes, "boards": info["boards"]}
                    if info.get("peripherals"):
                        detail["peripherals"] = info["peripherals"]
                    if codes or detail["boards"] or detail.get("peripherals"):
                        archive.setdefault("cartridge", []).append(detail)
                for serial, revision in sorted(headers.get(digest, {}).items()):
                    archive.setdefault("cartridge", []).append({
                        "headerCodes": [serial],
                        "source": {"name": "Libretro", "url": LIBRETRO_DB, "revision": revision},
                    })
                    has_header = True
            coverage[market] += int(has_header)
    return coverage


def _indexes(directory):
    folder, revision = THUMBNAILS["megadrive"]
    repo = folder.replace(" ", "_")
    urls = {
        "mame-megadriv.xml": MAME_RAW + MAME_FILE,
        "thumbs-megadrive.json": f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1",
        "digital-press.html": DIGITAL_PRESS,
    }
    indexes, issues = {}, []
    for name, url in urls.items():
        try:
            indexes[name] = read_index(directory / name, url)
        except (OSError, ValueError) as error:
            issues.append(f"{name}: {error}")
    return indexes, issues


def seed_megadrive(html_path=None, report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    directory = sources or SOURCE_DIRECTORY
    html = html_path.read_bytes() if html_path else read_index(directory / "retail.html", HTML_URL).content
    catalog = parse_retail_list(html, reference.get("compilations"))
    aliases = retail.read_aliases(REFERENCE.with_name("megadrive_retail_aliases.csv"))
    indexes, warnings = _indexes(directory)
    categories = sega_retro_scans(directory)
    warnings.extend(error for _, _, _, error in categories if error)
    source_indexes = [*indexes.values(), *(item for _, _, values, _ in categories for item in values)]
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest} for source in source_indexes]
    mame = list(cartridge_records(indexes["mame-megadriv.xml"].content)) if "mame-megadriv.xml" in indexes else []
    verified = reference.get("verifiedArchives", [])
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.megadrive-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            archives = retail.read_archives(connection, *SYSTEM, verified)
            roms = {row.signature: row.sha1 for row in connection.execute(
                VERIFIED_ROM_SQL, {"signatures": [archive["signature"] for archive in archives]},
            )}
            retail.match_archives(catalog, archives, aliases, verified, markets=ARCHIVE_MARKETS)
            related = list(mame_matches(catalog, archives, roms, mame))
            retail.match_archives(catalog, archives, aliases, [*verified, *related], markets=ARCHIVE_MARKETS)
            headers = add_cartridge_details(
                catalog, roms, mame, rdb_cartridge_records(connection, roms.values(), (THUMBNAILS["megadrive"][0],)),
            )
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={"Sega Genesis"},
                                     thumbnails=THUMBNAILS, thumbnail_key="megadrive", country_markets=SCAN_MARKETS)
            add_scans(catalog, categories, indexes.get("digital-press.html"), aliases,
                      reviewed_titles=reference.get("scanTitles"))
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, ARCHIVE_MARKETS)
            metadata = catalog["summary"]["metadata"]
            metadata["releases"]["romHeader"] = sum(headers.values())
            for market, count in headers.items():
                metadata["byMarket"][market]["romHeader"] = count
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=SYSTEM, secondary_platform=None, formats=("vgm", "vgz", "gym"),
                aliases=[{"edition": alias["edition"], "title": alias["archiveTitle"]} for alias in aliases],
            )
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            if publish_catalog:
                retail.publish(connection, catalog, "megadrive")
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
