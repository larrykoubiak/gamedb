"""CLI for importing recovered historical identity sources into staging."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from gamedb.database import create_database_engine

from .importer import HistoricalImporter


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb import-history")
    parser.add_argument("--python-gamedb", type=Path, required=True)
    parser.add_argument("--legacy-archive", type=Path)
    parser.add_argument("--patch-workbook", type=Path)
    args = parser.parse_args(argv)
    old_database_url = os.environ.get("OLD_GAMEDB")
    if not old_database_url:
        parser.error("OLD_GAMEDB must contain the legacy SQLAlchemy connection URL")
    counts = HistoricalImporter(
        create_database_engine(), old_database_url, args.python_gamedb,
        args.legacy_archive, args.patch_workbook,
    ).execute()
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
