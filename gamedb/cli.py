"""Current CLI; connection settings come from .env, libpq PG* variables or .pgpass."""

import argparse
import json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync-sources", help="Refresh source mappings, DATs and persistent archive IDs.")
    parse = commands.add_parser("parse-names", help="Parse current archive names using their IDs.")
    parse.add_argument("--reparse", action="store_true", help="Recompute all current names.")
    sync = commands.add_parser("sync", help="Synchronize source identities, then parse names.")
    sync.add_argument("--reparse", action="store_true", help="Recompute all current names.")
    args = parser.parse_args(argv)

    # Keep help available without installing database dependencies.
    from gamedb.config import load_environment

    load_environment()
    from gamedb.romvault.importer import parse_archive_names, sync_sources

    results = {}
    if args.command in ("sync-sources", "sync"):
        results["sources"] = sync_sources()
    if args.command in ("parse-names", "sync"):
        results["names"] = parse_archive_names(reparse=args.reparse)
    print(json.dumps(results, indent=2))
    return 0
