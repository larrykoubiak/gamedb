"""Compatibility command; use python -m gamedb parse-names instead."""

import sys

from gamedb.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["parse-names", *sys.argv[1:]]))
