"""Match the Nintendo 64 retail catalog to verified Game Pak inventory."""

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1
import json
import re
from xml.etree import ElementTree

from gamedb.catalog import retail
from gamedb.catalog.addons import ADDONS, add_retail_addon
from gamedb.catalog.cartridges import COUNTRY_MARKETS, VERIFIED_ROM_SQL, read_verified_rom
from gamedb.catalog.megadrive import Cartridge, add_cartridge_details
from gamedb.catalog.n64_media import MANUAL_SOURCES, add_manuals, add_reviewed_artwork
from gamedb.catalog.n64_rom import N64_ROM_LIMIT, V64_MAGIC, big_endian, swap_words
from gamedb.catalog.n64_source import HTML_URL, MARKETS, parse_retail_list
from gamedb.catalog.references import MAME, MAME_RAW, read_index
from gamedb.catalog.retail_media import add_descriptions_and_art
from gamedb.catalog.soundtracks import add_soundtracks
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine


PLATFORM = "n64"
SYSTEM = ("Nintendo", "Nintendo 64")
ARCHIVE_MARKETS = {market: retail.ARCHIVE_MARKETS[market] for market in MARKETS if market != "BR"} | {"BR": {"BR"}}
SCAN_MARKETS = COUNTRY_MARKETS | {"Brazil": "BR", "BRA": "BR", "BR": "BR"}
THUMBNAILS = {PLATFORM: ("Nintendo - Nintendo 64", "ff0badea277f2d2d15e9008b04f1a0fd6abc40a3")}
REFERENCE = PROJECT_ROOT / "reference/n64_retail.json"
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/n64-retail"
MAME_FILE = "n64.xml"
EXCLUDED = re.compile(r"\([^()]*(?:proto(?:type)?|bootleg|pirate|unl(?:icensed)?|beta|sample|demo|hack)\b", re.I)


def cartridge_records(content):
    software_list = ElementTree.fromstring(content)
    if software_list.get("name") != PLATFORM:
        raise ValueError("Unexpected MAME Nintendo 64 software list")
    for item in software_list.findall("software"):
        label = item.findtext("description", "")
        if EXCLUDED.search(label):
            continue
        names, territories = [], set()
        for name in label.split(" ~ "):
            local = re.search(r"\s*\(([^()]*)\)$", name)
            if local:
                territories.update(SCAN_MARKETS[region.strip()] for region in local[1].split(",")
                                   if region.strip() in SCAN_MARKETS)
                name = name[:local.start()]
            names.append(name)
        info = {node.get("name"): node.get("value") for node in item.findall("info")}
        codes = []
        for serial in (info.get("serial") or "").split(","):
            if match := re.fullmatch(r"\s*(NUS-[A-Z0-9]+-([A-Z]{3})(?:-[0-9]+)?)\s*", serial):
                codes.append({"code": match[1], "market": SCAN_MARKETS.get(match[2])})
        for part in item.findall("part"):
            roms = part.findall("dataarea[@name='rom']/rom")
            if len(roms) != 1 or not (digest := roms[0].get("sha1")):
                continue
            name = item.get("name")
            boards = [pcb.get("value") for pcb in part.findall("feature[@name='pcb']") if pcb.get("value")]
            yield Cartridge(digest, item.get("cloneof", name), tuple(names), frozenset(territories), {
                "source": {"name": "MAME", "url": MAME + MAME_FILE, "record": name},
                "boards": boards, "productCodes": codes, "title": info.get("alt_title"),
            })


def _word_swapped_digest(rom):
    content = read_verified_rom(rom, max_size=N64_ROM_LIMIT)
    if content is None:
        return None
    try:
        return rom.sha1 if content[:4] == V64_MAGIC else sha1(swap_words(big_endian(content))).hexdigest()
    except ValueError:
        return None


def _mame_fingerprints(roms, cache_path):
    # No-Intro stores native .z64 images. MAME hashes 16-bit byte-swapped images.
    cached = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    pending = {rom.sha1: rom for rom in roms if rom.sha1 not in cached}
    if pending:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for original, swapped in zip(pending, pool.map(_word_swapped_digest, pending.values()), strict=True):
                if swapped:
                    cached[original] = swapped
        retail.write_report(cache_path, cached)
    return {rom.signature: cached.get(rom.sha1, rom.sha1) for rom in roms}


def match_game_paks(connection, catalog, records, reference, directory=SOURCE_DIRECTORY):
    aliases, reviewed = reference.get("archiveAliases", ()), reference.get("verifiedArchives", ())
    labels = [*reviewed, *reference.get("archiveEligibility", ())]
    archives = retail.read_archives(connection, *SYSTEM, labels)
    verified = list(connection.execute(
        VERIFIED_ROM_SQL, {"signatures": [archive["signature"] for archive in archives]},
    ))
    roms = _mame_fingerprints(verified, directory / "mame-fingerprints.json")
    archives = [archive for archive in archives if archive["signature"] in roms]
    retail.match_archives(catalog, archives, aliases, reviewed, markets=ARCHIVE_MARKETS)
    related = list(retail.cartridge_group_matches(catalog, archives, roms, records, markets=ARCHIVE_MARKETS))
    retail.match_archives(catalog, archives, aliases, [*reviewed, *related], markets=ARCHIVE_MARKETS)
    add_cartridge_details(catalog, roms, records, markets=ARCHIVE_MARKETS)
    native_titles = defaultdict(set)
    for record in records:
        if (title := record.evidence["title"]) and "JP" in record.markets:
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


def _indexes(directory, urls):
    indexes, warnings = {}, []
    for name, url in urls.items():
        try:
            indexes[name] = read_index(directory / name, url)
        except (OSError, ValueError) as error:
            warnings.append(f"{name}: {error}")
    return indexes, warnings


def seed_n64(html_path=None, report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    directory = sources or SOURCE_DIRECTORY
    html = html_path.read_bytes() if html_path else read_index(directory / "retail.html", HTML_URL).content
    catalog = parse_retail_list(html, additional_releases=reference.get("additionalReleases", ()),
                                regional_corrections=reference.get("regionalCorrections"))
    folder, revision = THUMBNAILS[PLATFORM]
    repo = folder.replace(" ", "_")
    indexes, warnings = _indexes(directory, {
        MAME_FILE: MAME_RAW + MAME_FILE,
        "thumbs-n64.json": f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1",
        **MANUAL_SOURCES,
    })
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest} for source in indexes.values()]
    records = list(cartridge_records(indexes[MAME_FILE].content)) if MAME_FILE in indexes else []
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.n64-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            match_game_paks(connection, catalog, records, reference, directory)
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={"Nintendo 64"},
                                     thumbnails=THUMBNAILS, thumbnail_key=PLATFORM, country_markets=SCAN_MARKETS)
            add_reviewed_artwork(catalog, reference.get("artwork", ()))
            warnings.extend(add_manuals(catalog, indexes, reference, directory))
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, ARCHIVE_MARKETS)
            catalog["summary"]["mediaTitles"] = dict(Counter(
                field for game in catalog["games"]
                for field in ("manuals", "artwork") if any(release.get(field) for release in game["releases"])
            ))
            soundtrack_aliases = [*reference.get("soundtrackAliases", ()), *(
                {"edition": alias["edition"], "title": alias["archiveTitle"]}
                for alias in reference.get("archiveAliases", ())
            )]
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=SYSTEM, secondary_platform=None, formats=("usf", "miniusf"),
                aliases=soundtrack_aliases,
            )
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            add_retail_addon(connection, catalog, directory, ADDONS[PLATFORM], ARCHIVE_MARKETS)
            if publish_catalog:
                retail.publish(connection, catalog, PLATFORM)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
