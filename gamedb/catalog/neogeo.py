"""Publish the original Neo Geo cartridge catalog against the Arcade inventory."""

from collections import Counter, defaultdict
import csv
from hashlib import md5
import json
import re
from urllib.parse import quote

from sqlalchemy import text

from gamedb.arcade.bundle import partition_link_firmware
from gamedb.catalog import retail
from gamedb.catalog.addons import DISC_ADDONS, add_retail_addon
from gamedb.catalog.retail_media import _scope_launchbox
from gamedb.catalog.software_identity import SOFTWARE_KEY_SQL
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.vgm.inventory import NEOGEO_COLLECTION


PLATFORM = "neogeo"
REFERENCE = PROJECT_ROOT / "reference"
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/neogeo-retail"
ROSTER = REFERENCE / "neogeo_retail.csv"
MEDIA = REFERENCE / "neogeo_retail_media.json"
SOURCE = {
    "name": "Wikipedia contributors, List of Neo Geo games",
    "url": "https://en.wikipedia.org/wiki/Special:PermanentLink/1378818686#Games",
    "revision": "1378818686",
    "license": "https://creativecommons.org/licenses/by-sa/4.0/",
}
MARKETS = ("MVS", "AES")
SET_NAME = re.compile(r"[a-z0-9_]{1,24}")


def arcade_sets_sql(names):
    """Retrieve live software keys and versioned install signatures for reviewed sets."""
    return f"""
        SELECT a.shortname AS "setName", r.display_title AS title,
               split_part(a.source_key, ':', 1) AS emulator, a.version,
               a.install_signature AS "installSignature", software.id AS "softwareId",
               {SOFTWARE_KEY_SQL} AS "softwareKey",
               a.plan->>'complete' = 'true' AS complete,
               a.plan->>'emulationStatus' AS "emulationStatus",
               a.plan->'missing' AS missing
        FROM catalog.arcade_release a
        JOIN catalog.release r ON r.id = a.release_id
        JOIN catalog.software_release membership ON membership.release_id = r.id
        JOIN catalog.software software ON software.id = membership.software_id
        JOIN catalog.system system ON system.id = software.system_id
        JOIN catalog.title title ON title.id = software.preferred_title_id
        WHERE a.shortname = ANY({names})
          AND system.manufacturer_name = 'Various' AND system.system_name = 'Arcade'
          AND (a.plan->'facts' @> '[{{"key":"hardware","value":"SNK Neo Geo"}}]'
               OR a.shortname IN ('kf2k3pcb', 'ms5pcb', 'svcpcb'))
          AND NOT EXISTS (
              SELECT FROM jsonb_array_elements(a.plan->'facts') AS fact
              WHERE fact->>'key' IN ('dump_modification', 'release_status')
          )
    """


def split_field(field):
    return [value.strip() for value in field.split("|") if value.strip()]


def load_roster(path=ROSTER):
    games = {}
    claimed_sets = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            shortname = row["set"]
            if shortname in games or not SET_NAME.fullmatch(shortname):
                raise ValueError(f"Invalid Neo Geo set {shortname!r}")
            title = row["title"]
            key = md5(f"neogeo\x1f{shortname}".encode(), usedforsecurity=False).hexdigest()
            aliases = split_field(row["aliases"])
            game = {
                "key": key, "title": title, "setName": shortname,
                "aliases": [{"title": name} for name in aliases],
                "developer": row["developer"], "publisher": row["publisher"],
                "genres": split_field(row["genres"]),
                "source": {"url": SOURCE["url"], "record": title},
                "releases": [],
            }
            for market, date, sets in (
                ("MVS", row["mvs"], [shortname, *split_field(row["mvs_sets"])]),
                ("AES", row["aes"], split_field(row["aes_sets"])),
            ):
                if not date:
                    continue
                for name in sets:
                    if not SET_NAME.fullmatch(name) or claimed_sets.setdefault(name, shortname) != shortname:
                        raise ValueError(f"Conflicting Neo Geo set {name!r} for {title}")
                game["releases"].append({
                    "key": f"{key}-{market.lower()}", "market": market, "edition": title,
                    "titles": [title], "date": date, "channel": "cartridge",
                    "setNames": list(dict.fromkeys(sets)),
                    "productCodes": split_field(row[f"{market.lower()}_serials"]),
                    "genre": " · ".join(game["genres"]),
                })
            if not game["releases"]:
                raise ValueError(f"No cartridge release documented for {title}")
            games[shortname] = game
    return {"source": SOURCE, "games": list(games.values())}


def add_arcade_sets(games, records):
    by_name = defaultdict(list)
    for row in records:
        source = f"{row['emulator']}:{row['version']}"
        missing, optional = partition_link_firmware(source, row["setName"], row["missing"])
        availability = {field: value for field, value in row.items() if field != "missing"}
        availability.update(complete=bool(row["complete"] or (optional and not missing)),
                            singleCabinet=bool(optional), issues=sorted({item["reason"] for item in missing}))
        by_name[row["setName"]].append(availability)
    for game in games:
        for release in game["releases"]:
            if "setNames" not in release:
                continue
            names = release["setNames"]
            releases = [row for name in names for row in by_name[name]]
            release["arcadeSets"] = sorted(releases, key=lambda row: (
                not row["complete"], row["emulationStatus"] == "preliminary", row["emulator"] != "FBNeo",
                names.index(row["setName"]), row["version"], row["installSignature"],
            ))
            release["status"] = "matched" if releases else "unmatched"


def add_media(catalog, media):
    thumbs = media["thumbnails"]
    repository, revision = thumbs["repository"], thumbs["revision"]
    for game in catalog["games"]:
        record = media["games"].get(game["setName"], {})
        for release in game["releases"]:
            assets = record.get(release["market"], {})
            art = {}
            for kind, asset in assets.get("artwork", {}).items():
                if isinstance(asset, str):
                    asset = {
                        "url": f"https://raw.githubusercontent.com/{repository}/{revision}/{quote(asset)}",
                        "source": {"name": "Libretro", "url": f"https://github.com/{repository}", "revision": revision},
                    }
                art[kind] = asset
            release["artwork"] = art
            release["manuals"] = assets.get("manuals", [])


def add_soundtracks(connection, catalog, media):
    for game in catalog["games"]:
        game.pop("soundtrackLinks", None)
    if not connection.execute(text("SELECT to_regclass('vgm.asset') IS NOT NULL")).scalar_one():
        return
    published = dict(connection.execute(text("""
        SELECT source_name, key FROM vgm.soundtrack album
        WHERE collection = :collection AND EXISTS (
            SELECT FROM vgm.asset asset WHERE asset.soundtrack_key = album.key
              AND asset.detail->>'kind' = 'track' AND asset.detail->>'format' IN ('vgm', 'vgz')
        )
    """), {"collection": NEOGEO_COLLECTION}).all())
    for game in catalog["games"]:
        record = media["games"].get(game["setName"], {}).get("soundtrack")
        if record and (key := published.get(record["name"])):
            releases = [release["key"] for release in game["releases"]]
            game["soundtrackLinks"] = [{
                "key": key, "title": record["title"], "collection": NEOGEO_COLLECTION,
                "sourceUrl": record["sourceUrl"], "releases": releases, "titleMatches": releases,
            }]


def coverage(catalog):
    counts = Counter()
    by_market = {market: Counter() for market in MARKETS}
    for game in catalog["games"]:
        for release in game["releases"]:
            bucket = by_market[release["market"]]
            bucket.update({
                "releases": 1,
                "sets": int(bool(release["arcadeSets"])),
                "installable": int(any(row["complete"] for row in release["arcadeSets"])),
                "artwork": int(bool(release["artwork"])),
                "manuals": int(bool(release["manuals"])),
            })
        counts.update({
            "games": 1,
            "descriptions": int(bool(game.get("description"))),
            "artwork": int(any(release["artwork"] for release in game["releases"])),
            "manuals": int(any(release["manuals"] for release in game["releases"])),
            "soundtracks": int(bool(game.get("soundtrackLinks"))),
        })
    return {**counts, "byMarket": {market: dict(bucket) for market, bucket in by_market.items()}}


def seed_neogeo(report=None, *, publish_catalog=False):
    catalog = load_roster()
    media = json.loads(MEDIA.read_text(encoding="utf-8"))
    add_media(catalog, media)
    catalog["enrichmentSources"] = media["sources"]
    names = sorted({name for game in catalog["games"] for release in game["releases"] for name in release["setNames"]})
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.neogeo-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            records = connection.execute(text(arcade_sets_sql("CAST(:names AS text[])")), {"names": names}).mappings()
            add_arcade_sets(catalog["games"], [dict(row) for row in records])
            descriptions = {game["title"]: {"descriptionId": record["launchboxId"]}
                            for game in catalog["games"]
                            if (record := media["games"].get(game["setName"], {})).get("launchboxId")}
            _scope_launchbox(connection, catalog, descriptions, platforms={"Arcade", "SNK Neo Geo AES", "SNK Neo Geo MVS"})
            for game in catalog["games"]:
                if description := media["games"].get(game["setName"], {}).get("description"):
                    game["description"] = description
            add_soundtracks(connection, catalog, media)
            catalog["summary"] = coverage(catalog)
            markets = {**retail.ARCHIVE_MARKETS, "MVS": set(), "AES": set()}
            add_retail_addon(connection, catalog, SOURCE_DIRECTORY, DISC_ADDONS[PLATFORM], markets)
            if publish_catalog:
                retail.publish(connection, catalog, PLATFORM)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"revision": SOURCE["revision"], "published": publish_catalog, **catalog["summary"]}
