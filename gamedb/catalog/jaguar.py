"""Publish the original Atari Jaguar cartridge catalog."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from sqlalchemy import text

from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine

from . import retail
from .cartridges import VERIFIED_ROM_SQL
from .references import MAME, MAME_RAW, read_index
from .retail_media import _manual_key, add_descriptions_and_art, add_manuals
from .retail_source import cell_text, credit_for_market, regional_credits, remove_citations, title_and_aliases
from .soundtracks import add_soundtracks


PLATFORM = "jaguar"
SYSTEM = ("Atari", "Jaguar")
LAUNCHBOX_PLATFORM = "Atari Jaguar"
REVISION = 1374827177
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
SOURCE = {"name": "Wikipedia contributors",
          "url": f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#Cartridge"}
MARKETS = {"NA": {"NA", "US"}, "PAL": {"EU", "AU"}, "JP": {"JP"}}
MANUALS_URL = "https://www.digitpress.com/library/manuals/jaguar/"
THUMBNAILS = {PLATFORM: ("Atari - Jaguar", "2c8767a7de7422fc42ee1e2e2ecb9baf0eadc27e")}
REFERENCE = PROJECT_ROOT / "reference/jaguar_retail.json"
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/jaguar-retail"

TOSEC_ARCHIVES = text(f"""
    SELECT signature.sha1_set_digest AS signature, software.id AS "softwareId",
           {retail.SOFTWARE_KEY_SQL} AS "softwareKey", package.archive_name AS "archiveName",
           file.sha1_hex AS sha1
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    JOIN catalog.software_release member ON member.software_id = software.id
    JOIN catalog.release_content_signature signature ON signature.release_id = member.release_id
    JOIN catalog.release_package part ON part.release_id = signature.release_id
    JOIN catalog.package package ON package.id = part.package_id
    JOIN catalog.package_file file ON file.package_id = package.id
    WHERE system.manufacturer_name = :manufacturer AND system.system_name = :system
      AND signature.package_count = 1 AND signature.rom_count = 1
      AND package.source_collection = 'TOSEC' AND package.resolved_path IS NOT NULL
      AND file.sha1_verified AND file.sha1_hex = ANY(CAST(:sha1 AS text[]))
""")


def _key(*parts):
    return sha256("\0".join(("gamedb:jaguar-retail", *parts)).encode()).hexdigest()[:32]


def _game(row):
    title_cell, developer_cell, publisher_cell, *dates, _ = row.find_all(["td", "th"], recursive=False)
    title, aliases = title_and_aliases(title_cell)
    aliases = [{"title": alias["title"], "regions": [market for market, regions in MARKETS.items()
                                                   if regions.intersection(alias["regions"])]}
               for alias in aliases]
    credits = {"developer": regional_credits(developer_cell), "publisher": regional_credits(publisher_cell)}
    game = {"key": _key("game", title), "title": title, "aliases": aliases, "releases": [],
            **{field: credit_for_market(entries) for field, entries in credits.items()}}
    for (market, regions), cell in zip(MARKETS.items(), dates, strict=True):
        remove_citations(cell)
        date = cell_text(cell)
        if date.casefold() == "unreleased":
            continue
        if not re.search(r"\b19\d{2}\b", date):
            raise ValueError(f"Unexpected {market} release date for {title!r}: {date!r}")
        titles = [alias["title"] for alias in aliases if market in alias["regions"]] or [title]
        local_credits = {field: value for field, entries in credits.items()
                         if (value := credit_for_market(entries, regions))}
        game["releases"].append({
            "key": _key("release", title, market), "edition": title, "market": market,
            "titles": titles, "date": date, "channel": "cartridge", **local_credits,
            "creditSources": dict.fromkeys(local_credits, SOURCE),
        })
    return game


def parse_retail_list(html):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    heading = soup.find(id="Cartridge")
    table = heading.find_next("table", class_="wikitable") if heading else None
    rows = table.find_all("tr") if table else []
    if len(rows) != 52:
        raise ValueError("Expected 50 Atari Jaguar cartridge rows")
    cells = rows[1].find_all("th")
    for cell in cells:
        remove_citations(cell)
    if tuple(map(cell_text, cells)) != ("NA", "EU", "JP"):
        raise ValueError("Unexpected Jaguar release columns")
    games = [_game(row) for row in rows[2:]]
    if len({game["title"] for game in games}) != len(games) or any(not game["releases"] for game in games):
        raise ValueError("Invalid or duplicate Jaguar titles")
    return {"source": {**SOURCE, "revision": REVISION, "sha256": sha256(html).hexdigest(), "rowCount": len(games),
                       "license": "https://creativecommons.org/licenses/by-sa/4.0/"},
            "games": sorted(games, key=lambda game: game["title"].casefold())}


def _no_intro_archives(connection):
    archives = retail.read_archives(connection, *SYSTEM)
    roms = {row.signature: PurePosixPath(row.member_path).suffix.lower() for row in connection.execute(
        VERIFIED_ROM_SQL, {"signatures": [archive["signature"] for archive in archives]},
    )}
    # The .rom and .j64 DATs contain duplicate labels for different file layouts.
    native = {tuple(archive["archiveNames"]) for archive in archives if roms.get(archive["signature"]) == ".j64"}
    return [archive for archive in archives if archive["signature"] in roms and (
        roms[archive["signature"]] == ".j64" or tuple(archive["archiveNames"]) not in native
    )]


def _reviewed_archives(connection, mame, reviews):
    if not reviews:
        return [], []
    software = {entry.attrib["name"]: entry for entry in ElementTree.fromstring(mame).findall("software")}
    expected = {}
    for review in reviews:
        part = software[review["mame"]].find("part[@interface='jaguar_cart']")
        roms = part.findall("dataarea/rom") if part is not None else []
        if len(roms) != 1 or not re.fullmatch(r"[0-9a-f]{40}", roms[0].get("sha1", "")):
            raise ValueError(f"Expected one Jaguar ROM for {review['mame']!r}")
        expected[review["archiveName"], roms[0].attrib["sha1"]] = review
    archives, verified = [], []
    for row in connection.execute(TOSEC_ARCHIVES, {
        "manufacturer": SYSTEM[0], "system": SYSTEM[1], "sha1": [digest for _, digest in expected],
    }).mappings():
        if (review := expected.get((row["archiveName"], row["sha1"]))) is None:
            continue
        archives.append({"title": review["edition"], "signature": row["signature"],
                         "softwareId": row["softwareId"], "softwareKey": row["softwareKey"],
                         "archiveNames": [row["archiveName"]], "regions": review["regions"],
                         "revisions": [], "versions": [], "channel": "cartridge"})
        verified.extend({"edition": review["edition"], "market": market, "signature": row["signature"],
                         "evidence": f"{MAME}jaguar.xml ({review['mame']}, SHA-1 {row['sha1']})"}
                        for market, countries in retail.ARCHIVE_MARKETS.items() if countries.intersection(review["regions"]))
    return archives, verified


def _manuals(catalog, html, reference):
    scans = {_manual_key(cell_text(link)): urljoin(MANUALS_URL, quote(link["href"], encoding="windows-1252"))
             for link in BeautifulSoup(html, "html.parser").select('a[href$=".pdf"]')}
    aliases = reference.get("manualAliases", {})
    shared = reference.get("palManuals", {})
    for game in catalog["games"]:
        title = game["title"]
        if title in reference.get("excludedDigitalPressManuals", {}):
            continue
        if url := scans.get(_manual_key(aliases.get(title, title))):
            markets = ("NA", "PAL") if title in shared else ("NA",)
            regions = ["US", "EU"] if title in shared else ["US"]
            for market in markets:
                yield {"edition": title, "market": market, "name": f"{title} — manual", "regions": regions,
                       "language": shared.get(title, "English"), "format": "PDF", "url": url,
                       "source": "Digital Press", "sourceUrl": MANUALS_URL}


def _add_cartridge_art(catalog, scans):
    releases = {(release["edition"], release["market"]): release
                for game in catalog["games"] for release in game["releases"]}
    for scan in scans:
        artwork = releases[scan["edition"], scan["market"]].setdefault("artwork", {})
        artwork["cartridge"] = {**scan["image"], "basis": "reviewed-image"}


def seed_jaguar(html_path=None, report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    directory = sources or SOURCE_DIRECTORY
    html = html_path.read_bytes() if html_path else read_index(directory / "retail.html", HTML_URL).content
    catalog = parse_retail_list(html)
    folder, revision = THUMBNAILS[PLATFORM]
    repo = folder.replace(" ", "_")
    indexes = {"jaguar.xml": read_index(directory / "jaguar.xml", MAME_RAW + "jaguar.xml")}
    warnings = []
    for filename, url in {
        "digitpress.html": MANUALS_URL,
        "thumbs-jaguar.json": f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1",
    }.items():
        try:
            indexes[filename] = read_index(directory / filename, url)
        except (OSError, ValueError) as error:
            warnings.append(f"{filename}: {error}")
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest} for source in indexes.values()]
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.jaguar-retail'))" if publish_catalog
                                       else "SET TRANSACTION READ ONLY")
            archives = _no_intro_archives(connection)
            tosec, verified = _reviewed_archives(connection, indexes["jaguar.xml"].content, reference["tosecArchives"])
            retail.match_archives(catalog, archives + tosec, reference.get("archiveAliases", ()), verified)
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={LAUNCHBOX_PLATFORM},
                                     thumbnails=THUMBNAILS, thumbnail_key=PLATFORM)
            _add_cartridge_art(catalog, reference.get("cartridgeArt", ()))
            manual_links = [{**manual, "market": market} for manual in reference.get("manuals", ())
                            for market in manual["markets"]]
            if "digitpress.html" in indexes:
                manual_links = [*_manuals(catalog, indexes["digitpress.html"].content, reference), *manual_links]
            add_manuals(catalog, {}, reviewed=manual_links)
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=SYSTEM, secondary_platform=None, formats=("mod",),
            )
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog)
            catalog["summary"]["mediaTitles"] = dict(Counter(
                field for game in catalog["games"] for field in ("manuals", "artwork")
                if any(release.get(field) for release in game["releases"])
            ))
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            if publish_catalog:
                retail.publish(connection, catalog, PLATFORM)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
