"""Import a LaunchBox ZIP, or report candidate coverage without changing catalog."""
import argparse
import json
from pathlib import Path

from gamedb.database import create_database_engine
from .importer import LaunchBoxImporter, SOURCE_URL
from .report import write_report

DEFAULT_PLATFORM_MAP = Path(__file__).resolve().parents[2] / "reference/launchbox_platforms.csv"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gamedb import-launchbox")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("import", help="snapshot a downloaded Metadata.zip into staging")
    load.add_argument("zip", type=Path)
    load.add_argument("--source-url", default=SOURCE_URL)
    images = commands.add_parser("images", help="import image references from an existing ZIP snapshot")
    images.add_argument("zip", type=Path)
    media = commands.add_parser("media", help="fill missing artwork using imported image references")
    media.add_argument("--username", default="default")
    report = commands.add_parser("report", help="write candidate coverage; leave catalog unchanged")
    report.add_argument("--output", required=True, type=Path, help="new report directory")
    report.add_argument("--platform-map", type=Path, default=DEFAULT_PLATFORM_MAP)
    report.add_argument("--revision", help="ZIP SHA-256; defaults to latest imported snapshot")
    args = parser.parse_args(argv)
    engine = create_database_engine()
    try:
        if args.command == "import":
            result = LaunchBoxImporter(engine, args.zip, args.source_url).execute()
        elif args.command == "images":
            from .images import import_images
            result = import_images(engine, args.zip)
        elif args.command == "media":
            from gamedb.catalog.launchbox_media import fill_launchbox_media
            result = fill_launchbox_media(engine, args.username)
        else:
            result = write_report(engine, args.output, args.platform_map, args.revision)
    finally:
        engine.dispose()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
