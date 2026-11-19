"""Inventory eXo collections and publish immutable staging snapshots."""
import argparse
import json
from pathlib import Path
import sys

from gamedb.database import create_database_engine
from .importer import publish
from .inventory import scan


def main(argv=None):
    parser = argparse.ArgumentParser(prog='gamedb import-exo')
    parser.add_argument('root', type=Path, nargs='?', default=Path('/mnt/exo'))
    parser.add_argument('--dry-run', action='store_true', help='Inventory and link assets without opening a database connection')
    parser.add_argument('--jobs', type=int, default=8, help='Concurrent media ZIP directory readers')
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error('--jobs must be positive')

    def progress(message):
        print(message, file=sys.stderr, flush=True)

    inventory = scan(args.root, args.jobs, progress)
    if args.dry_run:
        result = {'source_revision': inventory.revision, **inventory.counts()}
    else:
        result = publish(create_database_engine(), args.root, inventory, progress)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
