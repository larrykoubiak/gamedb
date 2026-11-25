"""Publish the US PlayStation retail catalog and its verified Redump sets."""

from collections import defaultdict
import json

from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.vgm.inventory import BROWSER_AUDIO

from . import retail
from .disc_catalog import redump_archives
from .playstation_media import add_manuals, apply_reviewed_artwork, manual_inventory
from .playstation_source import retail_list
from .references import read_index
from .retail_media import add_descriptions_and_art
from .soundtracks import add_soundtracks


SYSTEM = ("Sony", "PlayStation")
MARKETS = {"NA": {"US"}}
THUMBNAILS = {"playstation": ("Sony - PlayStation", "ccee75c7744d81676b6725307aca27ef6be6231a")}
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/playstation-retail"
REFERENCE = PROJECT_ROOT / "reference/playstation_retail.json"
SOUNDTRACK_FORMATS = {"psf", "minipsf", "xa", "genh"} | {suffix[1:] for suffix in BROWSER_AUDIO}

def match_releases(catalog, archives, reviews):
    archive_titles = defaultdict(list)
    for archive in archives:
        if "US" in archive["regions"]:
            archive_titles[archive["title"]].append(archive)
    aliases, verified = [], []
    missing = {}
    for game in catalog["games"]:
        release, = game["releases"]
        review = reviews.get(game["source"]["record"], {})
        address = {"edition": release["edition"], "market": release["market"],
                   "evidence": review.get("evidence", game["source"]["url"])}
        for name in review.get("archiveTitles", ()):
            aliases.append({**address, "archiveTitle": name})
        if parts := review.get("verifiedTitles"):
            if unavailable := [part for part in parts if part not in archive_titles]:
                missing[release["key"]] = unavailable
            else:
                signatures = {archive["signature"] for part in parts for archive in archive_titles[part]}
                verified.extend({**address, "signature": signature} for signature in sorted(signatures))
    retail.match_archives(catalog, archives, aliases, verified, markets=MARKETS)
    # Some retail boxes ship exactly the same discs as their standalone releases.
    original = {archive["archiveNames"][0]: archive for game in catalog["games"]
                for release in game["releases"] for archive in release.get("archives", ())
                if len(archive["archiveNames"]) == 1}
    for game in catalog["games"]:
        release, = game["releases"]
        review = reviews.get(game["source"]["record"], {})
        if bundle := review.get("bundleDiscs"):
            if unavailable := [name for name in bundle if name not in original]:
                missing[release["key"]] = unavailable
            else:
                release.pop("candidates", None)
                release.update(status="matched", archives=[
                    {**original[name], "basis": "reviewed-retail-bundle", "evidence": review["evidence"]}
                    for name in bundle
                ])
        if unavailable := missing.get(release["key"]):
            release.pop("archives", None)
            release.pop("candidates", None)
            release.update(status="unmatched", reviewNote={"text": "Missing discs for " + ", ".join(unavailable)})
    retail.summarize_matches(catalog, len(archives), MARKETS)
    return aliases


def add_pressings(catalog, archives, reviews):
    claimed = {archive["signature"] for game in catalog["games"] for release in game["releases"]
               for archive in release.get("archives", ())}
    for game in catalog["games"]:
        release, = game["releases"]
        review = reviews.get(game["source"]["record"], {})
        if release["status"] != "matched" or not (pressings := review.get("pressings")):
            continue
        for archive in archives:
            pressing = pressings.get(archive["title"])
            if not pressing or "US" not in archive["regions"] or archive["signature"] in claimed:
                continue
            release["archives"].append({**archive, "basis": "reviewed-retail-pressing", "pressing": pressing["label"],
                                        "evidence": pressing.get("source", game["source"]["url"])})
            codes = dict.fromkeys((*release["productCodes"], *pressing.get("serials", ())))
            release["productCodes"] = list(codes)
            claimed.add(archive["signature"])


def seed_playstation(report=None, *, publish_catalog=False, sources=None):
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reviews = reference.get("games", {})
    directory = sources or SOURCE_DIRECTORY
    catalog, checklist = retail_list(directory, reviews)
    manuals, manual_sources = manual_inventory(directory, reference.get("supplementalManuals", {}))
    folder, revision = THUMBNAILS["playstation"]
    repo = folder.replace(" ", "_")
    thumbs = read_index(directory / "thumbs-playstation.json", max_bytes=24 * 1024**2,
                        url=f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1")
    catalog["enrichmentSources"] = [{"url": source.url, "sha256": source.digest}
                                    for source in (*checklist, thumbs, *manual_sources)]

    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.playstation-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            archives = redump_archives(connection, *SYSTEM, MARKETS["NA"])
            aliases = match_releases(catalog, archives, reviews)
            add_descriptions_and_art(connection, catalog, {"thumbs-playstation.json": thumbs}, reference,
                                     platforms={"Sony Playstation"}, thumbnails=THUMBNAILS, thumbnail_key="playstation")
            apply_reviewed_artwork(catalog, reviews)
            add_pressings(catalog, archives, reviews)
            add_manuals(catalog, manuals, reviews)
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, MARKETS)
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=SYSTEM, secondary_platform=None,
                formats=sorted(SOUNDTRACK_FORMATS),
                joshw_archive_bucket="psf",
                aliases=[{"edition": item["edition"], "title": item["archiveTitle"]} for item in aliases],
            )
            if publish_catalog:
                retail.publish(connection, catalog, "playstation")
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
