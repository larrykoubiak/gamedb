"""Inventory VGM and optionally publish playable and downloadable catalog media."""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path

from gamedb.config import ProjectEnvironment
from gamedb.database import create_database_engine

from .importer import publish, resolve, summarize
from .inventory import C64, PLAYSTATION, PS2, scan
from .tags import COMPOSER_TAG_FORMATS, PSF_VERSIONS, RELATED_PSF_VERSIONS, add_track_tags


def enrich(root, library, formats):
    def read_item(item):
        add_track_tags(root, item.assets, formats)

    items = iter(library)
    with ThreadPoolExecutor(max_workers=8) as pool:
        while batch := list(islice(items, 1024)):
            for _ in pool.map(read_item, batch):
                pass


def main(argv=None):
    ProjectEnvironment().load()
    parser = argparse.ArgumentParser(prog="gamedb import-vgm", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(
        os.environ.get("GAMEDB_VGM_ROOT") or "/mnt/synology/music/VGM/By Format"
    ))
    parser.add_argument("--report", type=Path, help="write a JSON Lines matching report")
    parser.add_argument("--publish", action="store_true", help="replace the VGM database inventory")
    args = parser.parse_args(argv)

    library = scan(args.root)
    if not library:
        parser.error(f"no soundtrack sets found under {args.root}")
    tag_sources = (item for item in library if item.system in {C64, PLAYSTATION, PS2})
    enrich(args.root, tag_sources, {"sid", *PSF_VERSIONS})
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            resolved = list(resolve(connection, library))

        tagged = (item for item, row in zip(library, resolved, strict=True)
                  if row["status"] == "matched"
                  or any(asset["format"] in COMPOSER_TAG_FORMATS for asset in item.assets))
        enrich(args.root, tagged, {"spc", "nsf", "gbs", *RELATED_PSF_VERSIONS, *COMPOSER_TAG_FORMATS})
        if args.publish:
            with engine.begin() as connection:
                publish(connection, library, resolved)
    finally:
        engine.dispose()
    if args.report:
        with args.report.open("w", encoding="utf-8") as stream:
            for item, row in zip(library, resolved, strict=True):
                print(json.dumps({**row, "assets": item.assets}, ensure_ascii=False), file=stream)
    print(json.dumps({"published": args.publish, **summarize(library, resolved)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
