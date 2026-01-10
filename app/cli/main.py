"""CLI entrypoints for GameDB."""

from __future__ import annotations

import argparse
import sys

from app.core.rdb.importer import RdbImporter
from app.db.session import SessionLocal, init_db


def cmd_init_db(_args: argparse.Namespace) -> int:
    init_db()
    print("Initialized database schema.")
    return 0


def cmd_import_rdb(args: argparse.Namespace) -> int:
    session = SessionLocal()
    try:
        importer = RdbImporter(
            session,
            source=args.source,
            skipped_log_path=args.skipped_log,
        )
        stats = importer.import_path(args.path, limit=args.limit)
        print(
            "Imported: "
            f"systems={stats.systems} "
            f"titles={stats.titles} "
            f"releases={stats.releases} "
            f"roms={stats.roms} "
            f"attributes={stats.attributes} "
            f"skipped_rows={stats.skipped_rows} "
            f"skipped_fields={stats.skipped_fields}"
        )
        return 0
    finally:
        session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gamedb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Create database tables.")
    init_parser.set_defaults(func=cmd_init_db)

    import_parser = subparsers.add_parser("import-rdb", help="Import .rdb files.")
    import_parser.add_argument("path", help="Path to a .rdb file or directory.")
    import_parser.add_argument("--source", default="libretro_rdb", help="Source label for attributes.")
    import_parser.add_argument("--limit", type=int, default=None, help="Optional row limit per file.")
    import_parser.add_argument(
        "--skipped-log",
        default=None,
        help="Optional log path for skipped rows.",
    )
    import_parser.set_defaults(func=cmd_import_rdb)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
