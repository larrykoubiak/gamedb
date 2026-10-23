"""CLI for importing reviewed integrated packages."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from gamedb.database import create_database_engine

from .importer import IntegratedImporter


DEFAULT_ROOT = Path(os.environ.get(
    "GAMEDB_INTEGRATED_ROOT", "/mnt/synology/backup/games/Undub"
))
DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "reference" / "integrated_releases.csv"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb import-integrated")
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    result = IntegratedImporter(
        create_database_engine(), args.root, args.manifest, args.jobs
    ).execute()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
