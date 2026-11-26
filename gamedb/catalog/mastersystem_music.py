"""Mirror reviewed SMS Power VGM packs and link them to their retail editions."""

from concurrent.futures import ThreadPoolExecutor
import fcntl
from http.client import HTTPException
import json
import os
from pathlib import Path
import re

from sqlalchemy import text

from gamedb.catalog.mastersystem_media import SMS_POWER, SOURCE_DIRECTORY
from gamedb.catalog.mastersystem_source import MARKETS
from gamedb.catalog.soundtracks import add_soundtracks
from gamedb.catalog.vgm_packs import save_pack
from gamedb.config import PROJECT_ROOT, ProjectEnvironment
from gamedb.database import create_database_engine
from gamedb.vgm.__main__ import enrich
from gamedb.vgm.importer import publish, resolve
from gamedb.vgm.inventory import MASTER_SYSTEM, SMS_POWER_COLLECTION, scan


MANIFEST = PROJECT_ROOT / "reference/mastersystem_soundtracks.json"
FORMATS = {"vgm", "vgz"}


def _packs():
    packs = {}
    for record in json.loads(MANIFEST.read_text(encoding="utf-8"))["packs"]:
        name = record["slug"]
        if (name in packs or not re.fullmatch(r"[A-Za-z0-9.]+-(?:SMS(?:-FM|-PSG)?|SG)", name)
                or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                or not 0 < record["size"] <= 5 * 1024 * 1024
                or not set() < set(record["markets"]) <= set(MARKETS)):
            raise ValueError(f"Invalid SMS Power VGM pack {name}")
        packs[name] = {
            **record, "name": name, "extension": ".zip", "sourceUrl": f"{SMS_POWER}/Music/{name}",
            "download": f"{SMS_POWER}/uploads/Music/{name}.zip",
        }
    return packs


def add_master_system_soundtracks(connection, catalog, aliases):
    add_soundtracks(
        connection, catalog, platform=MASTER_SYSTEM, secondary_platform=None,
        formats=("vgm", "vgz", "sgc", "kss"), excluded_collection=SMS_POWER_COLLECTION,
        aliases=[{"edition": alias["edition"], "title": alias["archiveTitle"]} for alias in aliases],
    )
    if connection.execute(text("SELECT to_regclass('vgm.soundtrack') IS NOT NULL")).scalar_one():
        published = dict(connection.execute(text("""
            SELECT source_name, key FROM vgm.soundtrack WHERE collection = :collection
        """), {"collection": SMS_POWER_COLLECTION}).all())
        games = {game["title"]: game for game in catalog["games"]}
        for name, pack in _packs().items():
            if name.endswith("-SG"):
                continue
            if not (key := published.get(name)) or not (game := games.get(pack["game"])):
                continue
            releases = [release["key"] for release in game["releases"]
                        if release["edition"] == game["title"] and release["market"] in pack["markets"]]
            if releases:
                game.setdefault("soundtrackLinks", []).append({
                    "key": key, "title": pack["title"], "collection": SMS_POWER_COLLECTION,
                    "releases": releases, "titleMatches": releases,
                })
    return {
        "titles": sum(bool(game.get("soundtrackLinks")) for game in catalog["games"]),
        "sets": sum(len(game.get("soundtrackLinks", ())) for game in catalog["games"]),
    }


def sync_soundtracks(root=None, *, workers=4):
    ProjectEnvironment().load()
    root = root or Path(os.environ.get("GAMEDB_VGM_ROOT") or "/mnt/synology/music/VGM/By Format")
    directory = root / SMS_POWER_COLLECTION
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".gamedb-vgm.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _sync_packs(root, directory, _packs(), workers)


def _sync_packs(root, directory, packs, workers):
    def mirror(record):
        try:
            cached = SOURCE_DIRECTORY / "music" / f"{record['name']}.zip"
            _, path = save_pack(record, directory, cached)
            return path.relative_to(root).as_posix(), None
        except (OSError, HTTPException, ValueError) as error:
            return None, str(error)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(zip(packs, pool.map(mirror, packs.values()), strict=True))
    failures = {name: error for name, (_, error) in results.items() if error}
    paths = {path for path, _ in results.values() if path}
    albums = scan(root, subdirectory=Path(SMS_POWER_COLLECTION), source_paths=paths)
    indexed = {album.source_name: album for album in albums if any(
        asset["kind"] == "track" and asset["format"] in FORMATS for asset in album.assets
    )}
    for name in packs.keys() - indexed.keys():
        failures.setdefault(name, "No readable VGM tracks in the reviewed archive")
    library = list(indexed.values())
    if library and not failures:
        for album in library:
            pack = packs[album.source_name]
            album.title = pack["title"]
            if pack["game"] != album.title:
                album.aliases = (pack["game"],)
            album.source_evidence = {"archive": pack["download"], "smsPower": pack["sourceUrl"]}
        enrich(root, library, FORMATS)
        engine = create_database_engine()
        try:
            with engine.begin() as connection:
                publish(connection, library, list(resolve(connection, library)), collection=SMS_POWER_COLLECTION)
        finally:
            engine.dispose()
    return {
        "packs": len(library), "tracks": sum(asset["kind"] == "track" for album in library for asset in album.assets),
        "published": bool(library) and not failures, "failures": failures,
    }
