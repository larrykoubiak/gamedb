"""Convenience dispatcher for the deriver, catalog, and explorer CLIs."""

from __future__ import annotations

import sys


HELP = """usage: gamedb {derive,parse-name,import-history,import-rdb,rebuild,promote-corrections,serve} ...

GameDB commands:
  derive       Build or selectively refresh the stable derived schema.
  parse-name   Inspect one archive filename using derivation rules.
  import-history  Snapshot recovered identity sources into staging.
  import-rdb    Snapshot compiled Libretro databases into staging.
  rebuild      Project catalog, identity, and scores from derived data.
  promote-corrections  Move reviewed working corrections into reference.
  serve        Run the explorer.

Dedicated entry points:
  python -m gamedb.derive ...
  python -m gamedb.catalog ...
  python -m gamedb.explorer ...
"""


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help"):
        print(HELP)
        return 0

    command, *remaining = arguments
    if command == "derive":
        from gamedb.derive.__main__ import main as derive_main

        return derive_main(remaining)
    if command == "parse-name":
        from gamedb.derive.__main__ import parse_name_main

        return parse_name_main(remaining)
    if command == "import-history":
        from gamedb.history.__main__ import main as history_main

        return history_main(remaining)
    if command == "import-rdb":
        from gamedb.rdb.__main__ import main as rdb_main

        return rdb_main(remaining)
    if command == "rebuild":
        from gamedb.catalog.cli import main as catalog_main

        return catalog_main([command, *remaining])
    if command == "promote-corrections":
        from gamedb.catalog.cli import main as catalog_main

        return catalog_main([command, *remaining])
    if command == "serve":
        from gamedb.explorer.__main__ import main as explorer_main

        return explorer_main(remaining)
    raise SystemExit(f"unknown command {command!r}\n\n{HELP}")
