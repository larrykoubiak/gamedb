"""Mirror reviewed soundtrack packs for early console retail games."""

import json
import os
from pathlib import Path

from gamedb.config import PROJECT_ROOT, ProjectEnvironment
from gamedb.database import create_database_engine
from gamedb.vgm.__main__ import enrich
from gamedb.vgm.importer import publish, resolve
from gamedb.vgm.inventory import EARLY_CONSOLE_COLLECTIONS, scan

from .second_generation import SOURCE_DIRECTORY
from .vgm_packs import save_pack


def sync_soundtracks(root=None):
    ProjectEnvironment().load()
    root = root or Path(os.environ.get("GAMEDB_VGM_ROOT") or "/mnt/synology/music/VGM/By Format")
    reference = PROJECT_ROOT / "reference/second_generation_soundtracks.json"
    packs = json.loads(reference.read_text(encoding="utf-8"))
    library = {}
    for collection, record in packs.items():
        directory = root / collection
        directory.mkdir(parents=True, exist_ok=True)
        status, path = save_pack(record, directory, SOURCE_DIRECTORY / "music" / f"{record['name']}.zip")
        (album,) = scan(root, subdirectory=Path(collection), source_paths={path.relative_to(root).as_posix()})
        if album.system != EARLY_CONSOLE_COLLECTIONS[collection] or not any(
            asset["kind"] == "track" for asset in album.assets
        ):
            raise ValueError(f"Invalid soundtrack pack for {collection}")
        album.title = record["name"]
        album.source_evidence = {"vgmrips": record["sourceUrl"], "archive": record["download"]}
        enrich(root, [album], {"vgm", "vgz"})
        library[collection] = album, status

    engine = create_database_engine()
    try:
        with engine.begin() as connection:
            for collection, (album, _) in library.items():
                publish(connection, [album], list(resolve(connection, [album])), collection=collection)
    finally:
        engine.dispose()
    return {collection: {"title": album.title, "archive": status,
                         "tracks": sum(asset["kind"] == "track" for asset in album.assets)}
            for collection, (album, status) in library.items()}
