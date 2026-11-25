"""Publish the Sega Saturn retail catalog with complete verified disc sets."""

from collections import Counter, defaultdict
import json
import re
from xml.etree import ElementTree

from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.vgm.inventory import BROWSER_AUDIO

from . import retail
from .cartridges import COUNTRY_MARKETS
from .disc_catalog import redump_archives
from .references import MAME, MAME_RAW, read_index
from .retail_media import add_descriptions_and_art
from .saturn_discs import complete_sets, disc_bundle, load_headers
from .saturn_media import COLLECTION_FILE, COLLECTION_URL, add_manuals, add_reviewed_covers
from .saturn_source import HTML_URL, MARKETS, parse_retail_list
from .soundtracks import add_soundtracks


PLATFORM = "saturn"
SYSTEM = ("Sega", "Saturn")
ARCHIVE_MARKETS = {**retail.ARCHIVE_MARKETS, "BR": {"BR"}, "KR": {"KR"}, "AS": {"TW", "AS"}}
SCAN_MARKETS = COUNTRY_MARKETS | {
    "BR": "BR", "Brazil": "BR", "KR": "KR", "Korea": "KR", "South Korea": "KR", "TW": "AS", "Taiwan": "AS",
}
THUMBNAILS = {PLATFORM: ("Sega - Saturn", "c512bd123db1307f77b50383fb478b4ddb14fd20")}
REFERENCE = PROJECT_ROOT / "reference/saturn_retail.json"
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/saturn-retail"
MAME_FILE = "saturn.xml"
FORMATS = {"ssf", "minissf", "adx", "ape", "genh", "xa"} | {suffix[1:] for suffix in BROWSER_AUDIO}
SERIAL = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", re.I)
PREVIEW = re.compile(r"\b(?:demo|sample|taikenban|prototype|beta|preview|unlicensed|hibaihin)\b", re.I)


def mame_records(content):
    root = ElementTree.fromstring(content)
    if root.get("name") != PLATFORM:
        raise ValueError("Unexpected MAME Sega Saturn software list")
    for item in root.findall("software"):
        label = item.findtext("description", "")
        if match := re.fullmatch(r"(.+?)\s*\(([^()]*)\)", label):
            regions = {SCAN_MARKETS[region.strip()] for region in match[2].split(",")
                       if region.strip() in SCAN_MARKETS}
            if not regions or PREVIEW.search(label):
                continue
            info = {node.get("name"): node.get("value") for node in item.findall("info")}
            serials = [token.strip() for token in (info.get("serial") or "").split(",")
                       if SERIAL.fullmatch(token.strip())]
            yield {"names": [*match[1].split(" ~ ")], "markets": regions, "serials": serials,
                   "nativeTitle": info.get("alt_title"), "record": item.get("name"),
                   "group": item.get("cloneof", item.get("name"))}


def _lookups(archives):
    names = defaultdict(dict)
    for archive in archives:
        for disc in archive["discs"]:
            names[disc["name"]].setdefault(archive["signature"], (archive, disc))
    return names


def _related_aliases(catalog, archives, records):
    """Apply exact regional MAME names or a unique reviewed software identity."""
    from .retail import _compact_title

    groups, labels = defaultdict(set), defaultdict(set)
    for record in records:
        for name in record["names"]:
            for market in record["markets"]:
                labels[market, _compact_title(name)].add(record["group"])
    for archive in archives:
        for market, regions in ARCHIVE_MARKETS.items():
            if regions.intersection(archive["regions"]):
                groups[market, _compact_title(archive["title"])].add(archive["softwareKey"])
    names = defaultdict(list)
    for archive in archives:
        names[archive["softwareKey"]].append(archive)
    owners = defaultdict(set)
    for game in catalog["games"]:
        for release in game["releases"]:
            for archive in release.get("archives", ()):
                owners[archive["softwareKey"]].add(game["key"])
    mame_names = defaultdict(set)
    for (market, spelling), families in labels.items():
        for family in families:
            mame_names[market, family].update(groups[market, spelling])
    for game in catalog["games"]:
        anchors = {archive["softwareKey"] for release in game["releases"] for archive in release.get("archives", ())
                   if owners[archive["softwareKey"]] == {game["key"]}}
        families = {family for release in game["releases"] for source in release.get("archives", ())
                    for family in labels[release["market"], _compact_title(source["title"])]}
        for release in game["releases"]:
            if release["status"] != "unmatched":
                continue
            market = release["market"]
            plausible = anchors.copy()
            if len(families) == 1:
                plausible |= mame_names[market, next(iter(families))]
            matches = {item["title"] for ident in plausible for item in names[ident]
                       if (not owners[ident] or owners[ident] == {game["key"]})
                       and ARCHIVE_MARKETS[market].intersection(item["regions"])}
            if len(matches) == 1:
                yield {"edition": release["edition"], "market": market, "archiveTitle": next(iter(matches)),
                       "evidence": f"{MAME}{MAME_FILE} and the verified Saturn software identity"}


def _reviewed_sets(catalog, archives, references):
    names = _lookups(archives)
    by_release = {(release["edition"], release["market"]): release
                  for game in catalog["games"] for release in game["releases"]}
    for review in references.get("discSets", ()):
        edition, market = review["edition"], review["market"]
        if (edition, market) not in by_release:
            raise ValueError(f"Unknown reviewed Saturn disc set {edition} ({market})")
        components = []
        for name in review["archives"]:
            matches = [(archive, disc) for archive, disc in names[name].values()
                       if ARCHIVE_MARKETS[market].intersection(archive["regions"])]
            if not matches:
                break
            components.append(min(matches, key=lambda item: item[0]["signature"]))
        else:
            yield (edition, market), disc_bundle(edition, components, pressing=review.get("label")), review["evidence"]


def match_releases(catalog, archives, headers, records, references):
    eligible = list(complete_sets(archives, headers))
    reviewed = list(_reviewed_sets(catalog, archives, references))
    eligible.extend(archive for _, archive, _ in reviewed)
    aliases = list(references.get("archiveAliases", ()))
    # Reviewed title-family variants can share a single retail edition.
    verified = [*references.get("verifiedArchives", ()), *(
        {"edition": edition, "market": market, "signature": archive["signature"], "evidence": evidence}
        for (edition, market), archive, evidence in reviewed
    )]
    retail.match_archives(catalog, eligible, aliases, verified, markets=ARCHIVE_MARKETS)
    reviewed_aliases = list(_related_aliases(catalog, eligible, records))
    if reviewed_aliases:
        aliases.extend(reviewed_aliases)
        retail.match_archives(catalog, eligible, aliases, verified, markets=ARCHIVE_MARKETS)
    for release in (release for game in catalog["games"] for release in game["releases"]):
        if release["status"] != "matched":
            continue
        serials = {headers[name]["serial"] for item in release["archives"] for name in item["archiveNames"]
                   if name in headers and SERIAL.fullmatch(headers[name]["serial"])}
        if serials:
            release["productCodes"] = sorted(serials)
        release["packagedDiscs"] = max(len(item["discs"]) for item in release["archives"])
    return aliases


def _add_native_titles(catalog, records):
    from .retail import _compact_title

    japanese = defaultdict(set)
    for record in records:
        if "JP" in record["markets"] and (title := record["nativeTitle"]):
            for name in record["names"]:
                japanese[_compact_title(name)].add(title)
    for game in catalog["games"]:
        names = {name for release in game["releases"] if release["market"] == "JP"
                 for archive in release.get("archives", ()) for name in japanese[_compact_title(archive["title"])]}
        known = {item["title"] for item in game["aliases"]}
        game["aliases"].extend({"title": title, "regions": ["JP"]} for title in sorted(names - known))


def merge_packaging_editions(catalog, reviews):
    """Keep a repackaged game disc under its original title and retain the retail editions."""
    games = {game["title"]: game for game in catalog["games"]}
    for review in reviews:
        game, edition = games[review["game"]], games[review["edition"]]
        market = review["market"]
        original, = [release for release in game["releases"]
                     if (release["edition"], release["market"]) == (game["title"], market)]
        release, = edition["releases"]
        if game is edition or release["market"] != market:
            raise ValueError(f"Invalid Saturn packaging edition: {review['edition']}")
        release["productCodes"] = review["productCodes"]
        shared = [{**archive, "basis": "reviewed-shared-disc", "evidence": review["evidence"]}
                  for archive in original.get("archives", ()) if archive["signature"] in review["signatures"]]
        if shared:
            release.update(status="matched", archives=shared, packagedDiscs=max(len(a["discs"]) for a in shared))
            release.pop("candidates", None)
            artwork = {kind: image for kind, image in original.get("artwork", {}).items() if kind != "boxart"}
            release["artwork"] = {**artwork, **release.get("artwork", {})}
            if review.get("sharedManual") and not release.get("manuals") and original.get("manuals"):
                release["manuals"] = [{**manual, "name": f"{manual['name']} — Original game manual"}
                                      for manual in original["manuals"]]
            for link in game.get("soundtrackLinks", ()):
                if original["key"] in link["releases"]:
                    link["releases"].append(release["key"])
        if edition.get("soundtrackLinks"):
            game.setdefault("soundtrackLinks", []).extend(edition["soundtrackLinks"])
        game["releases"].append(release)
        game.setdefault("formerKeys", []).append(edition["key"])
        catalog["games"].remove(edition)


def seed_saturn(html_path=None, report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    directory = sources or SOURCE_DIRECTORY
    html = html_path.read_bytes() if html_path else read_index(directory / "retail.html", HTML_URL).content
    catalog = parse_retail_list(html, compilations=reference.get("compilations", ()),
                                additional_releases=reference.get("additionalReleases", ()),
                                excluded=reference.get("exclude", {}),
                                omitted_releases=reference.get("omittedReleases"))
    folder, revision = THUMBNAILS[PLATFORM]
    repo = folder.replace(" ", "_")
    indexes, warnings = {}, []
    for filename, url in {
        MAME_FILE: MAME_RAW + MAME_FILE,
        COLLECTION_FILE: COLLECTION_URL,
        "thumbs-saturn.json": f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1",
    }.items():
        try:
            indexes[filename] = read_index(directory / filename, url)
        except (OSError, ValueError) as error:
            warnings.append(f"{filename}: {error}")
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest} for source in indexes.values()]
    records = list(mame_records(indexes[MAME_FILE].content)) if MAME_FILE in indexes else []
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.saturn-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            archives = redump_archives(connection, *SYSTEM, set().union(*ARCHIVE_MARKETS.values()))
            headers = load_headers(connection, archives, directory / "boot-headers.json")
            aliases = match_releases(catalog, archives, headers, records, reference)
            _add_native_titles(catalog, records)
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={"Sega Saturn"},
                                     thumbnails=THUMBNAILS, thumbnail_key=PLATFORM, country_markets=SCAN_MARKETS)
            add_reviewed_covers(catalog, reference.get("covers", ()))
            add_manuals(catalog, reference, indexes[COLLECTION_FILE].content if COLLECTION_FILE in indexes else None, aliases)
            add_soundtracks(
                connection, catalog, platform=SYSTEM, secondary_platform=None, formats=sorted(FORMATS),
                aliases=[{"edition": item["edition"], "title": item["archiveTitle"]} for item in aliases] +
                reference.get("soundtrackAliases", []),
            )
            merge_packaging_editions(catalog, reference.get("packagingEditions", ()))
            retail.summarize_matches(catalog, catalog["summary"]["eligibleArchives"], ARCHIVE_MARKETS)
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, ARCHIVE_MARKETS)
            catalog["summary"]["mediaTitles"] = dict(Counter(
                field for game in catalog["games"] for field in ("manuals", "artwork")
                if any(release.get(field) for release in game["releases"])
            ))
            catalog["summary"]["soundtracks"] = {
                "titles": sum(bool(game.get("soundtrackLinks")) for game in catalog["games"]),
                "sets": sum(len(game.get("soundtrackLinks", ())) for game in catalog["games"]),
            }
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            if publish_catalog:
                retail.publish(connection, catalog, PLATFORM)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
