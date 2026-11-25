"""Mirror the reviewed cartridge VGM packs and refresh their inventory."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
from http.client import HTTPException
import json
import os
from pathlib import Path

from sqlalchemy import text

from gamedb.catalog.neogeo import MEDIA, SOURCE_DIRECTORY, arcade_sets_sql, load_roster
from gamedb.catalog.vgm_packs import save_pack
from gamedb.config import ProjectEnvironment
from gamedb.database import create_database_engine
from gamedb.vgm.__main__ import enrich
from gamedb.vgm.importer import publish, resolve
from gamedb.vgm.inventory import NEOGEO_COLLECTION, scan


def sync_soundtracks(root=None, *, workers=4):
    ProjectEnvironment().load()
    root = root or Path(os.environ.get("GAMEDB_VGM_ROOT") or "/mnt/synology/music/VGM/By Format")
    media = json.loads(MEDIA.read_text(encoding="utf-8"))
    games = {game["setName"]: game for game in load_roster()["games"]}
    packs = {shortname: game["soundtrack"] for shortname, game in media["games"].items() if "soundtrack" in game}
    directory = root / NEOGEO_COLLECTION
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".gamedb-vgm.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _sync_packs(root, directory, games, packs, workers)


def _sync_packs(root, directory, games, packs, workers):
    saved, failures = {}, {}
    downloaded = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(save_pack, record, directory,
                            SOURCE_DIRECTORY / "music" / (shortname + record["extension"])): shortname
                for shortname, record in packs.items()}
        for job in as_completed(jobs):
            shortname = jobs[job]
            try:
                status, path = job.result()
                saved[path.stem] = (shortname, path.relative_to(root).as_posix())
                downloaded += status == "downloaded"
            except (OSError, HTTPException, ValueError) as error:
                failures[shortname] = str(error)
    library = []
    for album in scan(root, subdirectory=Path(NEOGEO_COLLECTION), source_paths={path for _, path in saved.values()}):
        shortname, _ = saved[album.source_name]
        if not any(asset["kind"] == "track" for asset in album.assets):
            failures[shortname] = "No readable VGM tracks in the reviewed archive"
            continue
        album.title = packs[shortname]["title"]
        album.source_evidence = {
            "vgmrips": packs[shortname]["sourceUrl"],
            "archive": packs[shortname]["download"],
            "set": shortname,
        }
        library.append(album)
    for name in saved.keys() - {album.source_name for album in library}:
        shortname, _ = saved[name]
        failures.setdefault(shortname, "Could not index the reviewed archive")
    if not library:
        raise ValueError("No readable Neo Geo VGM packs to publish")
    enrich(root, library, {"vgm", "vgz"})
    # Leave the existing publication readable if a refresh has source failures.
    if not failures:
        _publish_packs(library, games, saved)
    return {"packs": len(library), "downloaded": downloaded, "reused": len(saved) - downloaded,
            "tracks": sum(asset["kind"] == "track" for album in library for asset in album.assets),
            "published": not failures, "failures": failures}


def _publish_packs(library, games, saved):
    engine = create_database_engine()
    try:
        with engine.begin() as connection:
            resolved = list(resolve(connection, library))
            names = {shortname: [name for release in game["releases"] for name in release["setNames"]]
                     for shortname, game in games.items()}
            all_names = sorted(set().union(*names.values()))
            keys = {}
            for row in connection.execute(text(arcade_sets_sql("CAST(:names AS text[])")),
                                          {"names": all_names}).mappings():
                keys.setdefault(row["setName"], set()).add(row["softwareKey"])
            for album, record in zip(library, resolved, strict=True):
                shortname, _ = saved[album.source_name]
                targets = set().union(*(keys.get(name, ()) for name in names[shortname]))
                if record["target_key"]:
                    targets.add(record["target_key"])
                if targets:
                    target, *additional = sorted(targets)
                    record.update(status="matched", target_key=target, additional_target_keys=additional,
                                  match_evidence={**record["match_evidence"], **album.source_evidence})
            publish(connection, library, resolved, collection=NEOGEO_COLLECTION)
    finally:
        engine.dispose()
