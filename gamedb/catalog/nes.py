"""Build the curated NES and Famicom cartridge catalog."""

from collections import defaultdict
from dataclasses import dataclass
import json
import re
from xml.etree import ElementTree

from gamedb.catalog import retail
from gamedb.catalog.addons import ADDONS, add_retail_addon
from gamedb.catalog.cartridges import COUNTRY_MARKETS, VERIFIED_ROM_SQL, _markets_in_label, _serials
from gamedb.catalog.nes_media import add_manuals, manual_inventory
from gamedb.catalog.nes_rom import ines_fingerprints
from gamedb.catalog.nes_source import HTML_URL, parse_retail_list
from gamedb.catalog.references import MAME, MAME_RAW, read_index
from gamedb.catalog.retail_media import add_descriptions_and_art
from gamedb.catalog.soundtracks import add_soundtracks
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine


SYSTEM = ("Nintendo", "Nintendo Entertainment System")
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/nes-retail"
REFERENCE = PROJECT_ROOT / "reference/nes_retail.json"
THUMBNAILS = {"nes": ("Nintendo - Nintendo Entertainment System", "29607117d7dd3a0d42273dc5599ad5982cf5eb91")}
MAME_FILE = "nes.xml"
EXCLUDED_MAME = re.compile(r"\b(?:prototype|proto|bootleg|pirate|beta|sample|demo|hacked|FDS conversion)\b", re.I)


@dataclass(frozen=True)
class Cartridge:
    digest: tuple[str, str]
    group: str
    names: tuple[str, ...]
    markets: frozenset[str]
    evidence: dict


def cartridge_records(content):
    for software in ElementTree.fromstring(content).findall("software"):
        label = software.findtext("description", "")
        if EXCLUDED_MAME.search(label):
            continue
        markets = frozenset(_markets_in_label(label))
        info = {node.get("name"): node.get("value") for node in software.findall("info")}
        names = tuple(filter(None, (label.partition(" (")[0], info.get("alt_title"))))
        for part in software.findall("part"):
            areas = {area: [node for node in part.findall(f"dataarea[@name='{area}']/rom") if node.get("sha1")]
                     for area in ("prg", "chr")}
            if len(areas["prg"]) != 1 or len(areas["chr"]) > 1:
                continue
            if any(chip.get("status") == "baddump" for chips in areas.values() for chip in chips):
                continue
            digest = tuple(areas[area][0].get("sha1") if areas[area] else "" for area in ("prg", "chr"))
            boards = [model for pcb in part.findall("feature[@name='pcb']")
                      if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+){1,7}", model := pcb.get("value", ""))]
            yield Cartridge(digest, software.get("cloneof", software.get("name")), names, markets, {
                "source": {"name": "MAME", "url": MAME + MAME_FILE, "record": software.get("name")},
                "boards": boards, "serials": _serials(info.get("serial")),
            })


def _serial_market(code, markets):
    _, _, suffix = code.rpartition("-")
    if market := COUNTRY_MARKETS.get(suffix):
        return market
    if code.startswith("HVC-"):
        return "JP"
    return next(iter(markets)) if len(markets) == 1 else None


def add_cartridge_details(catalog, fingerprints, records):
    by_digest = defaultdict(list)
    for record in records:
        by_digest[record.digest].append(record)
    for game in catalog["games"]:
        for release in game["releases"]:
            market = release["market"]
            for archive in release.get("archives", ()):
                for record in by_digest[fingerprints.get(archive["signature"])]:
                    if market not in record.markets:
                        continue
                    evidence = {**record.evidence, "serials": [code for code in record.evidence["serials"]
                                                               if _serial_market(code, record.markets) == market]}
                    if evidence["serials"] or evidence["boards"]:
                        archive.setdefault("cartridge", []).append(evidence)


def seed_nes(html_path=None, report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    directory = sources or SOURCE_DIRECTORY
    html = html_path.read_bytes() if html_path else read_index(directory / "retail.html", HTML_URL).content
    verified = reference.get("verifiedArchives", [])
    catalog = parse_retail_list(html, reviewed_archives=verified)
    aliases = retail.read_aliases(REFERENCE.with_name("nes_retail_aliases.csv"))
    folder, revision = THUMBNAILS["nes"]
    thumb_repo = folder.replace(" ", "_")
    indexes = {
        "mame-nes.xml": read_index(directory / "mame-nes.xml", MAME_RAW + MAME_FILE),
        "thumbs-nes.json": read_index(directory / "thumbs-nes.json", max_bytes=24 * 1024**2,
                                      url=f"https://api.github.com/repos/libretro-thumbnails/{thumb_repo}/git/trees/{revision}?recursive=1"),
    }
    manuals, manual_sources = manual_inventory(directory)
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest}
                                    for source in (*indexes.values(), *manual_sources)]
    hardware = list(cartridge_records(indexes["mame-nes.xml"].content))
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.nes-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            archives = retail.read_archives(connection, *SYSTEM, verified)
            roms = list(connection.execute(VERIFIED_ROM_SQL, {"signatures": [archive["signature"] for archive in archives]}))
            banks = ines_fingerprints(directory / "rom-fingerprints.json", roms)
            fingerprints = {rom.signature: (bank["prg"], bank["chr"]) for rom in roms
                            if (bank := banks.get(rom.sha1)) is not None}
            retail.match_archives(catalog, archives, aliases, verified)
            related = list(retail.cartridge_group_matches(catalog, archives, fingerprints, hardware))
            retail.match_archives(catalog, archives, aliases, [*verified, *related])
            add_cartridge_details(catalog, fingerprints, hardware)
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={SYSTEM[1]},
                                     thumbnails=THUMBNAILS, thumbnail_key="nes")
            add_manuals(catalog, manuals, aliases)
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog)
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=SYSTEM, secondary_platform=None, formats=("nsf", "nsfe", "vgm", "vgz"),
                aliases=[{"edition": alias["edition"], "title": alias["archiveTitle"]} for alias in aliases],
            )
            add_retail_addon(connection, catalog, directory, ADDONS["nes"], retail.ARCHIVE_MARKETS)
            if publish_catalog:
                retail.publish(connection, catalog, "nes")
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
