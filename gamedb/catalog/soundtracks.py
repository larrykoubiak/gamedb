"""Resolve music sets against verified retail editions."""

from collections import defaultdict
from datetime import datetime
from pathlib import PurePosixPath
import re

from sqlalchemy import text

from gamedb.vgm.joshw import COLLECTION, EDITION, supports_version, superseded_sources, title_revision
from gamedb.vgm.matching import reviewed_titles, spelling_key


SNES = ("Nintendo", "Super Nintendo Entertainment System")
SUFAMI = ("Nintendo", "Sufami Turbo")
RIP_DATE = re.compile(r"\(((?:19|20)\d{2}(?:-\d{2}){0,2})\)")
PLAYSTATION_PREVIEW = re.compile(r"\b(?:demo|preview|prototype|trial|taikenban|sampler|homebrew|unlicensed)\b", re.I)
RIP_MARKETS = {"JP": "JP", "JPN": "JP", "US": "NA", "USA": "NA", "EU": "PAL", "EUR": "PAL", "PAL": "PAL",
               "BR": "BR", "KR": "KR"}

RETAIL_ALBUMS = text("""
    SELECT album.key, album.title, album.collection, album.source_name, album.platform,
           album.aliases, album.status, album.target_key,
           coalesce(to_jsonb(album)->'additional_target_keys', '[]') AS additional_target_keys
    FROM vgm.soundtrack album
    WHERE album.platform IN (
        CAST(:platform AS text[]), CAST(:secondary_platform AS text[])
    )
    AND album.collection IS DISTINCT FROM :excluded_collection
    AND EXISTS (
        SELECT FROM vgm.asset asset
        WHERE asset.soundtrack_key = album.key AND (
            (asset.detail->>'kind' = 'track' AND asset.detail->>'format' = ANY(CAST(:formats AS text[])))
            OR (asset.detail->>'kind' = 'archive' AND album.collection = :joshw_collection
                AND starts_with(album.source_name, CAST(:joshw_archive_prefix AS text)))
        )
    )
    ORDER BY album.collection, album.source_name, album.key
""")


def _title_key(name):
    return spelling_key(re.sub(r"(?<=\d)×(?=\d)", "x", name))


def _release_names(release):
    return {_title_key(name) for name in (*release["titles"], *(archive["title"]
            for archive in release.get("archives", ())))}


def _date(date):
    for format, output in (("%B %d, %Y", "%Y-%m-%d"), ("%B %Y", "%Y-%m"), ("%Y", "%Y")):
        try:
            return datetime.strptime(date, format).strftime(output)
        except ValueError:
            continue
    return ""


def _rip_markets(album):
    if album["collection"] != COLLECTION:
        return set()
    tail = PurePosixPath(album["source_name"]).name.rsplit(")", 1)[-1]
    return {RIP_MARKETS[tag] for tag in re.findall(r"\[([A-Z]+)\]", tail) if tag in RIP_MARKETS}


def _choose_title(candidates, primary, editions, album):
    if len(candidates) <= 1:
        return next(iter(candidates), None)
    match = RIP_DATE.search(PurePosixPath(album["source_name"]).name) if album["collection"] == COLLECTION else None
    if match:
        date = match[1]
        same_date = {edition for edition in candidates
                     if any(_date(release["date"]).startswith(date) for release in editions[edition][1])}
        if len(same_date) == 1:
            return same_date.pop()
    preferred = candidates & primary
    return preferred.pop() if len(preferred) == 1 else None


def _compatible_release(release, version, markets, platform):
    if markets and release["market"] not in markets:
        return False
    if not version:
        return True
    facts = [(kind, value) for archive in release["archives"]
             for kind, field in (("revision", "revisions"), ("version", "versions"))
             for value in archive[field]]
    return supports_version(platform, version, facts)


def link_soundtracks(catalog, albums, *, reviews=None, aliases=(), system=SNES, secondary_platform=SUFAMI):
    """Reuse the catalog's ownership evidence and reconcile explicit retail titles."""
    reviews = {} if reviews is None else reviews
    editions, titles, owners = {}, defaultdict(set), defaultdict(set)
    for game in catalog["games"]:
        staged = defaultdict(list)
        for release in game["releases"]:
            if release["status"] == "matched":
                staged[release["edition"]].append(release)
        for edition, releases in staged.items():
            editions[edition] = game, releases
            platforms = ((system, secondary_platform) if releases[0]["channel"] == "sufami-turbo"
                         else (system,))
            names = {_title_key(edition)}
            for release in releases:
                names.update(_release_names(release))
                for archive in release["archives"]:
                    owners[archive["softwareKey"]].add(edition)
            for platform in platforms:
                for name in names:
                    titles[platform, name].add(edition)

    for item in aliases:
        if item["edition"] in editions:
            titles[system, _title_key(item["title"])].add(item["edition"])

    fixed = superseded_sources(album["source_name"] for album in albums if album["collection"] == COLLECTION)
    for album in albums:
        title, version = title_revision(album["title"])
        platform = tuple(album["platform"])
        review = reviews.get((album["collection"], album["source_name"]))
        if ((review and not review["catalog_title"]) or album["status"] == "review" or EDITION.search(title)
                or (album["collection"] == COLLECTION and album["source_name"] in fixed)
                or (album["collection"] == COLLECTION and album["source_name"].startswith("psf/")
                    and PLAYSTATION_PREVIEW.search(album["source_name"]))
                or title.casefold().endswith(" (game genie)")
                or re.search(r"\[(?:mod|hack|unl)\]", album["source_name"], re.I)):
            continue
        primary = titles[platform, _title_key(review["catalog_title"] if review else title)]
        alternative = set().union(*(titles[platform, _title_key(name)] for name in album["aliases"]))
        native = set().union(*(owners[key] for key in (album["target_key"], *album["additional_target_keys"])))
        names = primary | alternative
        if names and native and not names & native:
            continue
        choices = names & native if names and native else names or native
        if not (edition := _choose_title(choices, primary, editions, album)):
            continue
        game, releases = editions[edition]
        matched_titles = {_title_key(title)}
        if album["collection"] == COLLECTION and not review:
            siblings = [release for other in sorted(alternative - {edition}) if editions[other][0] is game
                        for release in editions[other][1]]
            if siblings:
                releases = releases + siblings
                matched_titles.update(map(_title_key, album["aliases"]))
        region_tags = _rip_markets(album)
        eligible = [release for release in releases if _compatible_release(release, version, region_tags, platform)]
        if eligible:
            game.setdefault("soundtrackLinks", []).append({
                "key": album["key"], "title": album["title"], "collection": album["collection"],
                "releases": [release["key"] for release in eligible],
                "titleMatches": [release["key"] for release in eligible if matched_titles & _release_names(release)],
            })

    return {
        "titles": sum(bool(game.get("soundtrackLinks")) for game in catalog["games"]),
        "sets": sum(len(game.get("soundtrackLinks", ())) for game in catalog["games"]),
    }


def add_soundtracks(connection, catalog, aliases=(), *,
                    platform=SNES, secondary_platform=SUFAMI, formats=("spc",), joshw_archive_bucket=None,
                    excluded_collection=None):
    present = connection.execute(text("""
        SELECT to_regclass('vgm.soundtrack') IS NOT NULL AND to_regclass('vgm.asset') IS NOT NULL
    """)).scalar_one()
    albums = list(connection.execute(RETAIL_ALBUMS, {
        "platform": list(platform), "secondary_platform": list(secondary_platform) if secondary_platform else None,
        "formats": list(formats), "joshw_collection": COLLECTION,
        "joshw_archive_prefix": f"{joshw_archive_bucket}/" if joshw_archive_bucket else None,
        "excluded_collection": excluded_collection,
    }).mappings()) if present else []
    return link_soundtracks(catalog, albums, reviews=reviewed_titles(), aliases=aliases, system=platform,
                            secondary_platform=secondary_platform)
