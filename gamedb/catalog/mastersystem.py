"""Build the curated Master System and Mark III retail catalog."""

from collections import Counter
import json

from gamedb.catalog import retail
from gamedb.catalog.cartridges import COUNTRY_MARKETS, VERIFIED_ROM_SQL
from gamedb.catalog.mastersystem_media import (
    GAME_INDEX, MANUAL_INDEX, SOURCE_DIRECTORY, add_archive_manuals, add_reviewed_artwork, sms_power_matches,
)
from gamedb.catalog.mastersystem_music import add_master_system_soundtracks
from gamedb.catalog.mastersystem_source import HTML_URL, add_brazilian_releases, parse_retail_list
from gamedb.catalog.megadrive import add_cartridge_details, cartridge_records
from gamedb.catalog.megadrive_media import add_scans, sega_retro_scans
from gamedb.catalog.references import MAME_RAW, read_index
from gamedb.catalog.retail_media import add_descriptions_and_art
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine


PLATFORM = "mastersystem"
SYSTEM = ("Sega", "Master System")
ARCHIVE_MARKETS = retail.ARCHIVE_MARKETS | {"BR": {"BR"}}
SCAN_MARKETS = COUNTRY_MARKETS | {
    region: market for market, regions in ARCHIVE_MARKETS.items() for region in regions
} | {
    "Brazil": "BR", "UK": "PAL", "Euro": "PAL", "BX": "PAL", "GR": "PAL", "NO": "PAL", "PT": "PAL",
}
SCAN_CATEGORIES = {
    f"Master System {country} {kind} scans": (asset, country)
    for kind, asset in (("manual", "manual"), ("box", "boxart"))
    for country in ("US", "CA", "JP", "EU", "UK", "AU", "DE", "ES", "FR", "IT", "NL", "PT", "BR")
}
THUMBNAILS = {PLATFORM: ("Sega - Master System - Mark III", "3bb5e044786a3bc456c3f58c5d473748899b3dca")}
MAME_FILE = "sms.xml"
REFERENCE = PROJECT_ROOT / "reference/mastersystem_retail.json"


def _indexes(directory):
    folder, revision = THUMBNAILS[PLATFORM]
    repo = folder.replace(" ", "_")
    urls = {
        "mame-sms.xml": MAME_RAW + MAME_FILE,
        "thumbs-mastersystem.json": f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1",
        "smspower-games.html": GAME_INDEX,
        "archive-manuals.json": MANUAL_INDEX,
    }
    indexes, warnings = {}, []
    for name, url in urls.items():
        try:
            indexes[name] = read_index(directory / name, url)
        except (OSError, ValueError) as error:
            warnings.append(f"{name}: {error}")
    return indexes, warnings


def match_cartridges(connection, catalog, records, reference):
    reviewed = reference.get("verifiedArchives", [])
    aliases = reference.get("archiveAliases", [])
    archives = retail.read_archives(connection, *SYSTEM, reviewed)
    signatures = [archive["signature"] for archive in archives]
    roms = {row.signature: row.sha1 for row in connection.execute(VERIFIED_ROM_SQL, {"signatures": signatures})}
    archives = [archive for archive in archives if archive["signature"] in roms]
    retail.match_archives(catalog, archives, aliases, reviewed, markets=ARCHIVE_MARKETS)
    related = list(retail.cartridge_group_matches(catalog, archives, roms, records, markets=ARCHIVE_MARKETS))
    retail.match_archives(catalog, archives, aliases, [*reviewed, *related], markets=ARCHIVE_MARKETS)
    add_cartridge_details(catalog, roms, records, markets=ARCHIVE_MARKETS)


def seed_mastersystem(html_path=None, report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    directory = sources or SOURCE_DIRECTORY
    html = html_path.read_bytes() if html_path else read_index(directory / "retail.html", HTML_URL).content
    catalog = parse_retail_list(html, additional_releases=reference.get("additionalReleases", ()))
    indexes, warnings = _indexes(directory)
    scans = sega_retro_scans(directory, SCAN_CATEGORIES)
    warnings.extend(error for _, _, _, error in scans if error)
    source_indexes = [*indexes.values(), *(item for _, _, pages, _ in scans for item in pages)]
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest} for source in source_indexes]
    mame = indexes.get("mame-sms.xml")
    records = list(cartridge_records(mame.content, filename=MAME_FILE, regions=SCAN_MARKETS)) if mame else []
    aliases = reference.get("archiveAliases", ())
    games_source = indexes.get("smspower-games.html")
    archive_manuals = indexes.get("archive-manuals.json")

    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.mastersystem-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            match_cartridges(connection, catalog, records, reference)
            brazilian_editions = 0
            if games_source:
                matches = sms_power_matches(catalog, games_source.content, reference.get("smsPowerTitles", {}))
                brazilian_editions = add_brazilian_releases(catalog, matches)
                if brazilian_editions:
                    match_cartridges(connection, catalog, records, reference)
                for game in catalog["games"]:
                    if record := matches.get(game["key"]):
                        game["genres"] = sorted(record["genres"])
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={"Sega Master System"},
                                     thumbnails=THUMBNAILS, thumbnail_key=PLATFORM, country_markets=SCAN_MARKETS)
            add_scans(catalog, scans, aliases=aliases, reviewed_titles=reference.get("scanTitles"),
                      scan_categories=SCAN_CATEGORIES, scan_markets=SCAN_MARKETS)
            add_reviewed_artwork(catalog, reference.get("artwork", ()))
            if archive_manuals:
                add_archive_manuals(catalog, archive_manuals.content, aliases, reviewed=reference.get("scanTitles"))
            catalog["summary"]["supplementalBrazilianReleases"] = brazilian_editions
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, ARCHIVE_MARKETS)
            catalog["summary"]["mediaTitles"] = dict(Counter(
                field for game in catalog["games"]
                for field in ("manuals", "artwork") if any(release.get(field) for release in game["releases"])
            ))
            catalog["summary"]["soundtracks"] = add_master_system_soundtracks(connection, catalog, aliases)
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            if publish_catalog:
                retail.publish(connection, catalog, PLATFORM)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
