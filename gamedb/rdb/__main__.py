"""CLI for importing compiled Libretro databases into staging."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from gamedb.database import create_database_engine

from .importer import LibretroRdbImporter


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb import-rdb")
    parser.add_argument(
        "checkout", nargs="?", type=Path,
        default=Path(os.environ.get(
            "GAMEDB_LIBRETRO_DATABASE", "/data/libretro-database"
        )),
        help="libretro-database checkout (or its rdb directory)",
    )
    parser.add_argument(
        "--revision",
        help="explicit source revision when importing a detached RDB directory",
    )
    parser.add_argument("--source-url")
    parser.add_argument(
        "--replace", action="store_true",
        help="replace an existing snapshot of the same revision",
    )
    args = parser.parse_args(argv)
    result = LibretroRdbImporter(
        create_database_engine(), args.checkout, args.revision,
        args.source_url, args.replace,
    ).execute()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
