"""Build the curated PC Engine and TurboGrafx-16 HuCard catalog."""

from collections import Counter, defaultdict
import json
import re
from xml.etree import ElementTree

from gamedb.catalog import retail
from gamedb.catalog.addons import ADDONS, DISC_ADDONS, add_retail_addon
from gamedb.catalog.cartridges import COUNTRY_MARKETS, VERIFIED_ROM_SQL
from gamedb.catalog.megadrive import Cartridge, add_cartridge_details
from gamedb.catalog.pcengine_media import MANUAL_SOURCES, add_manuals, nec_retro_scans
from gamedb.catalog.pcengine_source import HTML_URL, MARKETS, parse_retail_list
from gamedb.catalog.references import MAME, MAME_RAW, read_index
from gamedb.catalog.retail_media import add_descriptions_and_art
from gamedb.catalog.soundtracks import add_soundtracks
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine


PLATFORM = "pcengine"
SYSTEM = ("NEC", "PC Engine / TurboGrafx-16")
ARCHIVE_MARKETS = {market: retail.ARCHIVE_MARKETS[market] for market in MARKETS}
THUMBNAILS = {PLATFORM: ("NEC - PC Engine - TurboGrafx 16", "33cbdb64bd99347ea47a5390584214f18d772b1f")}
SOFTWARE_LISTS = {"pce.xml": "JP", "tg16.xml": "NA"}
REFERENCE = PROJECT_ROOT / "reference/pcengine_retail.json"
MANUAL_REFERENCE = REFERENCE.with_name("pcengine_retail_manuals.json")
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/pcengine-retail"
EXCLUDED = re.compile(r"\([^()]*(?:prototype|proto|bootleg|pirate|beta|sample|demo|hack|unlicensed)\b", re.I)
REVISION = re.compile(r"\s+\((?:v\d+(?:\.\d+)*|rev(?:ision)? [^()]+)\)$", re.I)


def hucard_records(content, filename):
    market = SOFTWARE_LISTS[filename]
    software_list = ElementTree.fromstring(content)
    if software_list.get("name") != filename.removesuffix(".xml"):
        raise ValueError(f"Unexpected MAME HuCard software list {filename}")
    for item in software_list.findall("software"):
        title = item.findtext("description", "")
        if EXCLUDED.search(title):
            continue
        names = tuple(name.strip() for name in REVISION.sub("", title).split(" ~ "))
        info = {node.get("name"): node.get("value") for node in item.findall("info")}
        codes = [{"code": serial.strip(), "market": market} for serial in info.get("serial", "").split(",")
                 if re.fullmatch(r"[A-Za-z0-9-]+", serial.strip())]
        for part in item.findall("part"):
            roms = part.findall("dataarea[@name='rom']/rom")
            if len(roms) != 1 or not (digest := roms[0].get("sha1")):
                continue
            name = item.get("name")
            boards = [pcb.get("value") for pcb in part.findall("feature[@name='pcb']") if pcb.get("value")]
            yield Cartridge(digest, f"{market}:{item.get('cloneof', name)}", names, frozenset({market}), {
                "source": {"name": "MAME", "url": MAME + filename, "record": name},
                "boards": boards, "productCodes": codes, "title": info.get("alt_title"),
            })


def match_hucards(connection, catalog, records, reference):
    aliases, reviewed = reference.get("archiveAliases", []), reference.get("verifiedArchives", [])
    archives = retail.read_archives(connection, *SYSTEM, reviewed)
    signatures = [archive["signature"] for archive in archives]
    roms = {row.signature: row.sha1 for row in connection.execute(VERIFIED_ROM_SQL, {"signatures": signatures})}
    archives = [archive for archive in archives if archive["signature"] in roms]
    retail.match_archives(catalog, archives, aliases, reviewed, markets=ARCHIVE_MARKETS)
    related = list(retail.cartridge_group_matches(catalog, archives, roms, records, markets=ARCHIVE_MARKETS))
    retail.match_archives(catalog, archives, aliases, [*reviewed, *related], markets=ARCHIVE_MARKETS)
    add_cartridge_details(catalog, roms, records, markets=ARCHIVE_MARKETS)
    native_titles = defaultdict(set)
    for record in records:
        if (title := record.evidence["title"]) and record.markets == {"JP"}:
            native_titles[record.digest].add(title)
    for game in catalog["games"]:
        names = {name for release in game["releases"] if release["market"] == "JP"
                 for archive in release.get("archives", ()) for name in native_titles[roms[archive["signature"]]]}
        known = {alias["title"] for alias in game["aliases"]}
        game["aliases"].extend({"title": title, "regions": ["JP"]} for title in sorted(names - known))
        for release in game["releases"]:
            codes = {code for archive in release.get("archives", ()) for item in archive.get("cartridge", ())
                     for code in item.get("serials", ())}
            if codes:
                release["productCodes"] = sorted(codes)


def _indexes(directory):
    folder, revision = THUMBNAILS[PLATFORM]
    repo = folder.replace(" ", "_")
    urls = {
        **{filename: MAME_RAW + filename for filename in SOFTWARE_LISTS},
        "thumbs-pcengine.json": f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1",
        **MANUAL_SOURCES,
    }
    indexes, warnings = {}, []
    for name, url in urls.items():
        try:
            indexes[name] = read_index(directory / name, url)
        except (OSError, ValueError) as error:
            warnings.append(f"{name}: {error}")
    return indexes, warnings


def _add_hucard_soundtracks(connection, catalog, reference):
    aliases = [{"edition": alias["edition"], "title": alias["archiveTitle"]}
               for alias in reference.get("archiveAliases", ())]
    result = add_soundtracks(
        connection, catalog, platform=SYSTEM, secondary_platform=None, formats=("hes", "vgm", "vgz"),
        aliases=[*aliases, *reference.get("soundtrackAliases", ())],
    )
    # The original R-Type rip includes HC63007 and HC63009 in one playlist.
    rtype = next(game for game in catalog["games"] if game["title"] == "R-Type")
    for album in rtype.get("soundtrackLinks", ()):
        if album["collection"] == "JoshW" and album["title"] == "R-Type":
            album["releases"] = [release["key"] for release in rtype["releases"]]
    return result


def seed_pcengine(html_path=None, report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reference["manuals"] = json.loads(MANUAL_REFERENCE.read_text(encoding="utf-8"))
    directory = sources or SOURCE_DIRECTORY
    html = html_path.read_bytes() if html_path else read_index(directory / "retail.html", HTML_URL).content
    catalog = parse_retail_list(html, additional_releases=reference.get("additionalReleases", ()))
    indexes, warnings = _indexes(directory)
    scans, scan_warnings = nec_retro_scans(directory)
    warnings.extend(scan_warnings)
    sources_used = [*indexes.values(), *(source for _, source, _ in scans)]
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest} for source in sources_used]
    records = [record for filename in SOFTWARE_LISTS if filename in indexes
               for record in hucard_records(indexes[filename].content, filename)]
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.pcengine-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            match_hucards(connection, catalog, records, reference)
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={"NEC TurboGrafx-16"},
                                     thumbnails=THUMBNAILS, thumbnail_key=PLATFORM, country_markets=COUNTRY_MARKETS)
            add_manuals(catalog, indexes, reference, scans)
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, ARCHIVE_MARKETS)
            catalog["summary"]["mediaTitles"] = dict(Counter(
                field for game in catalog["games"]
                for field in ("manuals", "artwork") if any(release.get(field) for release in game["releases"])
            ))
            catalog["summary"]["soundtracks"] = _add_hucard_soundtracks(connection, catalog, reference)
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            for addon in (ADDONS[PLATFORM], DISC_ADDONS[PLATFORM]):
                add_retail_addon(connection, catalog, directory, addon, ARCHIVE_MARKETS)
            if publish_catalog:
                retail.publish(connection, catalog, PLATFORM)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
