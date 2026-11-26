"""Match documented SNES releases to original cartridge inventory and publish the result."""

import json

from gamedb.catalog import retail
from gamedb.catalog.addons import ADDONS, add_retail_addon
from gamedb.catalog.retail import enrichment_coverage, match_archives, read_aliases, write_report as write_report
from gamedb.catalog.cartridges import add_cartridge_evidence, cartridge_hashes, read_cartridge_roms
from gamedb.catalog.retail_media import add_descriptions_and_art, add_manuals
from gamedb.catalog.references import GAMING_ALEXANDRIA, SourceIndex, reference_indexes, snes_central_indexes
from gamedb.catalog.snes_source import load_html, parse_retail_list
from gamedb.catalog.soundtracks import add_soundtracks
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine


SYSTEM_NAME = "Super Nintendo Entertainment System"
SUFAMI_SYSTEM = "Sufami Turbo"
SUFAMI_HARDWARE = "sufami-turbo"
SUFAMI_SOURCE = {"name": "SNES Central", "url": "https://snescentral.com/article.php?id=0802"}
BASE_ARCHIVES = retail.base_archives_query("'Nintendo'", "'{}'")


def seed_snes(html_path=None, report=None, *, publish_catalog=False, sources=None, hash_cartridges=False):
    directory = PROJECT_ROOT / "reference"
    reference = json.loads((directory / "snes_retail.json").read_text(encoding="utf-8"))
    reviewed = read_aliases(directory / "snes_retail_aliases.csv")
    verified = reference["verifiedArchives"]
    catalog = parse_retail_list(load_html(html_path), reference["editions"], release_notes=reference["releaseNotes"],
                                additional_releases=reference.get("additionalReleases", ()))
    sources = sources or PROJECT_ROOT / "data/media/cache/snes-retail"
    indexes, warnings = reference_indexes(sources)
    indexes["ga-sfc-references.json"] = SourceIndex(
        GAMING_ALEXANDRIA, (directory / "snes_retail_japanese_manuals.json").read_bytes(),
    )
    central = list(snes_central_indexes(sources))
    catalog["enrichmentSources"] = [
        {"url": index.url, "sha256": index.digest} for index in (*indexes.values(), *(index for _, index in central))
    ]
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.snes-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            archives = retail.read_archives(connection, "Nintendo", SYSTEM_NAME, verified,
                                            secondary_system=SUFAMI_SYSTEM)
            match_archives(catalog, archives, reviewed, verified)
            roms = read_cartridge_roms(connection, catalog)
            fingerprint_path = sources / "cartridge-sha256.json"
            fingerprints = cartridge_hashes(fingerprint_path, roms, hash_cartridges)
            if hash_cartridges:
                write_report(fingerprint_path, fingerprints)
                missing = len({rom.sha1 for rom in roms.values()} - fingerprints.keys())
                if missing:
                    warnings.append(f"{missing} cartridge ROMs could not be fingerprinted from local ZIPs")
            add_cartridge_evidence(connection, catalog, roms, fingerprints, indexes, central, reference)
            add_descriptions_and_art(connection, catalog, indexes, reference)
            add_manuals(catalog, indexes, reference.get("manualAliases", ()), reference.get("manuals", ()))
            catalog["summary"]["metadata"] = enrichment_coverage(catalog)
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, read_aliases(directory / "snes_retail_soundtrack_aliases.csv"),
            )
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            for game in catalog["games"]:
                for release in game["releases"]:
                    if release["channel"] == SUFAMI_HARDWARE:
                        release["hardware"] = SUFAMI_HARDWARE
            catalog["addonSources"] = {SUFAMI_HARDWARE: SUFAMI_SOURCE}
            add_retail_addon(connection, catalog, sources, ADDONS["snes"], retail.ARCHIVE_MARKETS)
            if publish_catalog:
                retail.publish(connection, catalog, "snes")
    finally:
        engine.dispose()
    if report is not None:
        write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
