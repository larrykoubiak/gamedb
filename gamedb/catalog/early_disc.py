"""Publish retail catalogs for standalone disc consoles."""

from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from urllib.parse import quote, unquote, urljoin

from bs4 import BeautifulSoup

from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.vgm.inventory import BROWSER_AUDIO
from gamedb.vgm.joshw import RETAIL_BUCKETS

from . import retail
from .cartridges import COUNTRY_MARKETS
from .disc_catalog import DISC_SYSTEMS, approved_disc_matches, complete_disc_archives, redump_archives, verified_disc_archives
from .disc_variants import add_disc_variants
from .references import read_index
from .retail_media import _manual_key, add_descriptions_and_art, add_manuals, add_reviewed_artwork, release_names
from .retail_source import add_reviewed_releases, cell_text
from .soundtracks import add_soundtracks


SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/early-disc-retail"
SYSTEMS = {platform: DISC_SYSTEMS[platform] for platform in retail.OPTICAL_RETAIL_PLATFORMS}
MARKETS = {"pcfx": {"JP": retail.ARCHIVE_MARKETS["JP"]},
           "cd32": {market: retail.ARCHIVE_MARKETS[market] for market in ("PAL", "NA")},
           "3do": {**retail.ARCHIVE_MARKETS, "KR": {"KR"}, "BR": {"BR"}, "AS": {"TW", "HK", "AS"}},
           "playdia": {"JP": {"JP"}}, "pippin": {"JP": {"JP"}, "NA": {"US"}},
           "cdi": {**retail.ARCHIVE_MARKETS, "PAL": retail.ARCHIVE_MARKETS["PAL"] | {"BE", "PT", "DK", "NO", "FI", "CH"},
                   "KR": {"KR"}, "BR": {"BR"}, "WORLD": {"WORLD"}, "UNK": set()},
           "dreamcast": {**retail.ARCHIVE_MARKETS, "KR": {"KR"}, "BR": {"BR"}, "AS": {"TW", "HK", "AS"}},
           "playstation2": {"NA": {"US"}}, "gamecube": {"NA": {"US"}}}
SCAN_MARKETS = COUNTRY_MARKETS | {"KR": "KR", "Korea": "KR", "South Korea": "KR",
                                  "BR": "BR", "Brazil": "BR", "TW": "AS", "Taiwan": "AS"}
LAUNCHBOX = {"pcfx": "NEC PC-FX", "cd32": "Commodore Amiga CD32", "3do": "3DO Interactive Multiplayer",
             "dreamcast": "Sega Dreamcast", "playstation2": "Sony Playstation 2", "gamecube": "Nintendo GameCube",
             "cdi": "Philips CD-i"}
THUMBNAILS = {
    "pcfx": ("NEC - PC-FX", "1d82abb896d8dd5b125e70a3b7dd23118045ef2e"),
    "cd32": ("Commodore - CD32", "4bcde3a68b854bbb07add8b4f6403649b7fd75c6"),
    "3do": ("The 3DO Company - 3DO", "72a17178bbd4f3bc4cdcbadce746821dab84688f"),
    "dreamcast": ("Sega - Dreamcast", "28b140d16f188301ad697e5935c6dbb412a4ceda"),
    "playstation2": ("Sony - PlayStation 2", "9be559835a99124720badc6ec3ec4f3f2351deb3"),
    "gamecube": ("Nintendo - GameCube", "c0e778f3242811f31f4815ff2807022c1c5ac7bd"),
}
MANUAL_COLLECTIONS = {
    "3do": ("digitpress.html", "https://www.digitpress.com/library/manuals/3do/", "Digital Press", "NA"),
    "gamecube": ("gamecube-manual.json", "https://archive.org/metadata/NintendoGameCubeManuals",
                 "Nintendo GameCube Manuals", "NA"),
    "playstation2": ("ps2-manual.json",
                      "https://archive.org/metadata/kirklands-manual-labor-sony-playstation-2-usa-4k-version",
                      "Kirkland's Manual Labor", "NA"),
}
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
TRACK_FORMATS = {suffix[1:] for suffix in BROWSER_AUDIO} | {
    "mod", "xm", "it", "s3m", "okt", "med", "pro", "pt36", "ahx", "sid", "adx", "afc", "adp", "ads",
    "aix", "at3", "genh", "xa", "grn", "mpg",
    "ape", "aif", "aiff", "aifc",
    "dsf", "minidsf", "psf2", "minipsf2", "hps", "dsp", "ast", "brstm", "ss2", "vag", "vgmstream",
}


def _key(platform, *parts):
    return sha256("\0".join((f"gamedb:{platform}-retail", *parts)).encode()).hexdigest()[:32]


def _release(platform, title, market, date, names, *, edition=None):
    edition = edition or title
    return {"key": _key(platform, "release", title, edition, market), "edition": edition, "market": market,
            "titles": names, "date": date, "channel": "optical-disc"}


def _read_roster(platform, roster, review):
    games = {}
    source = roster["source"]
    rows = roster["rows"]
    notes = review.get("releaseNotes", {})
    if len(rows) != source["rowCount"]:
        raise ValueError(f"Incomplete {platform} retail roster")
    for row in rows:
        title = row["title"]
        if title in games or not title.strip():
            raise ValueError(f"Duplicate or empty {platform} retail title {title!r}")
        alternates = row.get("regionalTitles", {})
        aliases = row.get("aliases", [])
        credits = {field: row.get(field, {}) for field in ("developer", "publisher")}
        game = {"key": _key(platform, "game", title), "title": title, "releases": [], "genres": row.get("genres", []),
                "aliases": [*aliases, *({"title": name, "regions": [market]} for market, name in alternates.items()
                                        if name != title)],
                **{field: values.get("default", "") for field, values in credits.items()}}
        for market, date in row["releases"].items():
            if market in review.get("omittedMarkets", {}).get(title, ()):
                continue
            if market not in MARKETS[platform] or (date and not YEAR.search(date)):
                raise ValueError(f"Unexpected {market} release for {title!r}: {date}")
            names = [alternates.get(market, title), *(alias["title"] for alias in aliases
                     if not alias["regions"] or market in alias["regions"])]
            release = _release(platform, title, market, date, list(dict.fromkeys(names)))
            if accessories := row.get("requiredAccessories"):
                release["requiredAccessories"] = accessories
            local_credits = {field: value for field, values in credits.items()
                             if (value := values.get(market, values.get("default")))}
            release.update(local_credits, creditSources=dict.fromkeys(local_credits, source))
            if note := notes.get(title, {}).get(market):
                release["reviewNote"] = note
            game["releases"].append(release)
        games[title] = game
    add_reviewed_releases(games, review.get("additionalReleases", ()), markets=MARKETS[platform],
                          game_key=lambda title: _key(platform, "game", title),
                          make_release=lambda *args, **kwargs: _release(platform, *args, **kwargs))
    for former_title, title in review.get("mergedTitles", {}).items():
        if former_title in games or title not in games:
            raise ValueError(f"Invalid {platform} title merge {former_title!r} into {title!r}")
        game = games[title]
        game.setdefault("formerKeys", []).append(_key(platform, "game", former_title))
        if not any(alias["title"] == former_title for alias in game["aliases"]):
            game["aliases"].append({"title": former_title, "regions": []})
    if any(not game["releases"] for game in games.values()):
        raise ValueError(f"A {platform} title has no published release")
    return {"source": source, "games": sorted(games.values(), key=lambda game: game["title"].casefold())}


def _archive_aliases(catalog, review, field):
    titles = review.get(field, {})
    for game in catalog["games"]:
        for release in game["releases"]:
            for name in titles.get(release["edition"], ()):
                yield {"edition": release["edition"], "market": release["market"], "archiveTitle": name,
                       "evidence": catalog["source"]["url"]}


def _reviewed_cd32_discs(connection, regions, records):
    manufacturer, system = SYSTEMS["cd32"]
    for record in records:
        candidates = verified_disc_archives(
            connection, manufacturer, record.get("system", system), regions, "TOSEC-ISO",
            inferred_region="EU", archive_names=record["archives"],
        )
        yield from (archive for archive in candidates if archive["signature"] == record["signature"])


def _add_compilation_matches(catalog, inclusions):
    if not inclusions:
        return
    games = {game["title"]: game for game in catalog["games"]}
    for title, compilation in inclusions.items():
        pack = games[compilation]
        pack_markets = {release["market"] for release in pack["releases"] if release["status"] == "matched"}
        for release in games[title]["releases"]:
            if release["status"] == "unmatched" and release["market"] in pack_markets:
                release.update(status="matched", archives=[], includedIn={"key": pack["key"], "title": compilation})


def match_discs(connection, catalog, platform, review):
    markets = MARKETS[platform]
    regions = set().union(*markets.values(), {"WORLD"})
    raw = redump_archives(connection, *SYSTEMS[platform], regions)
    redump = list(complete_disc_archives(platform, raw, review.get("discSets", ()),
                                         standalone=review.get("standaloneDiscs", ())))
    verified = list(approved_disc_matches(redump, review.get("verifiedArchives", ())))
    aliases = list(_archive_aliases(catalog, review, "archiveTitles"))
    retail.match_archives(catalog, redump, aliases, verified, markets=markets)
    inclusions = review.get("includedIn", {})
    if platform in retail.SIXTH_GENERATION_PLATFORMS:
        if inclusions:
            _add_compilation_matches(catalog, inclusions)
            retail.summarize_matches(catalog, len(redump), markets)
        return
    remaining = {"source": catalog["source"], "games": [
        {**game, "releases": [release for release in game["releases"] if release["status"] == "unmatched"]}
        for game in catalog["games"]
    ]}
    # TOSEC's original CD32 game ISOs commonly omit a country. They can
    # supply the documented PAL release when the title has no Redump match.
    raw = verified_disc_archives(connection, *SYSTEMS[platform], regions, "TOSEC-ISO",
                                 inferred_region="EU" if platform == "cd32" else None)
    tosec = list(complete_disc_archives(platform, raw, review.get("tosecDiscSets", ())))
    reviewed_tosec = review.get("verifiedTosecArchives", ())
    if platform == "cd32" and reviewed_tosec:
        # Exact, reviewed discs can also be stored with the Amiga or CDTV collection.
        existing = {archive["signature"] for archive in tosec}
        tosec.extend(archive for archive in _reviewed_cd32_discs(connection, regions, reviewed_tosec)
                     if archive["signature"] not in existing)
    aliases = (*_archive_aliases(remaining, review, "archiveTitles"), *_archive_aliases(remaining, review, "tosecTitles"))
    approved = list(approved_disc_matches(tosec, reviewed_tosec))
    remaining_editions = {(release["edition"], release["market"]) for game in remaining["games"]
                          for release in game["releases"]}
    approved = [item for item in approved if (item["edition"], item["market"]) in remaining_editions]
    retail.match_archives(remaining, tosec, aliases, approved, markets=markets)
    _add_compilation_matches(catalog, inclusions)
    retail.summarize_matches(catalog, len(redump) + len(tosec), markets)


def _collection_manuals(catalog, html, collection, reference):
    filename, url, source, market = collection
    source_names = reference.get("manualAliases", {})
    claims = defaultdict(set)
    for game in catalog["games"]:
        for release in game["releases"]:
            if release["market"] == market:
                edition = release["edition"]
                for title in {edition, *release_names(release), *source_names.get(edition, ())}:
                    claims[_manual_key(title)].add(edition)
    if filename.endswith(".json"):
        yield from _archive_collection_manuals(html, url, source, market, claims)
        return
    excluded = set(reference.get("unavailableManuals", ()))
    for link in BeautifulSoup(html, "html.parser").select("a[href]"):
        href = link["href"]
        if not href.casefold().endswith(".pdf"):
            continue
        name = cell_text(link).removesuffix(".pdf") or PurePosixPath(unquote(href)).stem
        candidates = claims[_manual_key(name)]
        manual_url = urljoin(url, quote(href, safe="/%&'(),!:+-._~", encoding="windows-1252"))
        if len(candidates) == 1 and manual_url not in excluded:
            (edition,) = candidates
            yield {"edition": edition, "market": market, "name": f"{edition} — manual", "regions": [market],
                   "source": source, "sourceUrl": url, "format": "PDF", "url": manual_url}


def _archive_collection_manuals(content, url, source, market, claims):
    item = url.rsplit("/", 1)[-1]
    payload = json.loads(content)
    if payload.get("metadata", {}).get("identifier") != item:
        raise ValueError(f"Unexpected manual archive {item}")
    for doc in payload["files"]:
        filename = doc["name"]
        if doc.get("source") != "original" or not filename.lower().endswith(".pdf"):
            continue
        name = PurePosixPath(filename).stem
        match = re.fullmatch(r"(.+?)\s*\((?:USA|US)\)(?:\s*\(.*\))?", name)
        if not match or not doc.get("sha1") or not str(doc.get("size", "")).isdigit():
            continue
        if len(editions := claims[_manual_key(match[1])]) != 1:
            continue
        edition, = editions
        yield {"edition": edition, "market": market, "name": name + " — manual", "regions": ["US"],
               "language": "English", "format": "PDF", "source": source,
               "sourceUrl": f"https://archive.org/details/{item}",
               "url": f"https://archive.org/download/{item}/{quote(filename, safe='/')}",
               "sha1": doc["sha1"], "size": int(doc["size"])}


def _add_soundtrack_sources(catalog, platform, records):
    by_game = defaultdict(list)
    for record in records:
        by_game[record["game"]].append(record)
    for game in catalog["games"]:
        if sources := by_game.get(game["title"]):
            game["soundtrackSources"] = []
            for source in sources:
                url = source["url"]
                item = {"title": source["title"], "url": url,
                        "releases": [release["key"] for release in game["releases"]
                                     if release["market"] in source["markets"]]}
                if platform in RETAIL_BUCKETS and "size" in source and "revision" in source:
                    key = sha256(url.encode()).hexdigest()
                    item.update(size=source["size"], revision=source["revision"],
                                loadUrl=f"/related-media/joshw/{platform}/{game['key']}/{key}")
                game["soundtrackSources"].append(item)


def seed(platform, report=None, *, publish_catalog=False, sources=None):
    roster = json.loads((PROJECT_ROOT / f"reference/{platform}_retail_roster.json").read_text(encoding="utf-8"))
    review = json.loads((PROJECT_ROOT / f"reference/{platform}_retail.json").read_text(encoding="utf-8"))
    catalog = _read_roster(platform, roster, review)
    directory = sources or (SOURCE_DIRECTORY.parent / "sixth-generation-retail"
                            if platform in retail.SIXTH_GENERATION_PLATFORMS else SOURCE_DIRECTORY / platform)
    urls = {}
    if platform in THUMBNAILS:
        thumb_folder, revision = THUMBNAILS[platform]
        thumb_repo = thumb_folder.replace(" ", "_")
        urls[f"thumbs-{platform}.json"] = (
            f"https://api.github.com/repos/libretro-thumbnails/{thumb_repo}/git/trees/{revision}?recursive=1"
        )
    collection = MANUAL_COLLECTIONS.get(platform)
    if collection:
        filename, url, *_ = collection
        urls[filename] = url
    indexes, warnings = {}, []
    for filename, url in urls.items():
        try:
            indexes[filename] = read_index(directory / filename, url)
        except (OSError, ValueError) as error:
            warnings.append(f"{filename}: {error}")
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest} for source in indexes.values()]
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql(f"SELECT pg_advisory_xact_lock(hashtext('gamedb.{platform}-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            match_discs(connection, catalog, platform, review)
            if platform in retail.SIXTH_GENERATION_PLATFORMS:
                catalog["summary"]["prepatchedVariants"] = add_disc_variants(
                    connection, catalog, SYSTEMS[platform], MARKETS[platform], reviewed=review.get("prepatchedVariants", ()),
                )
            add_descriptions_and_art(connection, catalog, indexes, review, platforms={LAUNCHBOX.get(platform, SYSTEMS[platform][1])},
                                     thumbnails=THUMBNAILS, thumbnail_key=platform, country_markets=SCAN_MARKETS)
            if artwork := review.get("reviewedArtwork"):
                add_reviewed_artwork(catalog, platform, indexes, artwork, thumbnails=THUMBNAILS)
            manuals = list(review.get("manuals", ()))
            if collection and collection[0] in indexes:
                manuals.extend(_collection_manuals(catalog, indexes[collection[0]].content, collection, review))
            add_manuals(catalog, {}, reviewed=manuals)
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=SYSTEMS[platform], secondary_platform=None, formats=sorted(TRACK_FORMATS),
                aliases=review.get("soundtrackAliases", ()),
            )
            _add_soundtrack_sources(catalog, platform, review.get("soundtrackSources", ()))
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, MARKETS[platform])
            catalog["summary"]["mediaTitles"] = dict(Counter(
                field for game in catalog["games"] for field in ("manuals", "artwork")
                if any(release.get(field) for release in game["releases"])
            ))
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            if publish_catalog:
                retail.publish(connection, catalog, platform)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": roster["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
