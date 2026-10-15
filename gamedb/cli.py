"""Compatibility dispatcher for the standalone loader and explorer CLIs."""

from __future__ import annotations

import sys


HELP = """usage: gamedb {parse-name,rebuild,serve} ...

GameDB commands:
  parse-name   Inspect one archive filename using loader rules.
  rebuild      Plan or execute the loader pipeline.
  serve        Run the read-only explorer.

Dedicated entry points:
  python -m gamedb.load ...
  python -m gamedb.explorer ...
"""


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help"):
        print(HELP)
        return 0

    command, *remaining = arguments
    if command in ("parse-name", "rebuild"):
        from gamedb.load.cli import main as loader_main

        return loader_main([command, *remaining])
    if command == "serve":
        from gamedb.explorer.__main__ import main as explorer_main

        return explorer_main(remaining)
    raise SystemExit(f"unknown command {command!r}\n\n{HELP}")
