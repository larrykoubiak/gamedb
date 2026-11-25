"""Convenience dispatcher for the deriver, catalog, and explorer CLIs."""

from __future__ import annotations

import sys


HELP = """usage: gamedb <command> ...

GameDB commands:
  derive       Build or selectively refresh the stable derived schema.
  parse-name   Inspect one archive filename using derivation rules.
  import-history  Snapshot recovered identity sources into staging.
  import-integrated  Snapshot reviewed non-RomVault ZIP packages into staging.
  import-exo    Inventory eXo games, manuals and media into staging.
  import-vgm    Inventory and match video game soundtracks.
  import-rdb    Snapshot compiled Libretro databases into staging.
  import-launchbox  Snapshot LaunchBox metadata and report matching coverage.
  rebuild      Project catalog, identity, and scores from derived data.
  seed-snes    Match the pinned SNES retail list against the catalog.
  seed-megadrive  Build the Mega Drive retail catalog.
  seed-mastersystem  Build the Master System and Mark III retail catalog.
  seed-nes        Build the NES and Famicom retail catalog.
  seed-playstation  Build the US PlayStation retail catalog.
  seed-neogeo     Build the Neo Geo MVS and AES retail catalog.
  sync-snes-manuals  Download the manuals linked by the SNES retail catalog.
  sync-megadrive-manuals  Download the manuals linked by the Mega Drive retail catalog.
  sync-mastersystem-manuals  Download the manuals linked by the Master System retail catalog.
  sync-nes-manuals       Download the manuals linked by the NES and Famicom retail catalog.
  sync-playstation-manuals  Download the manuals linked by the PlayStation retail catalog.
  sync-neogeo-manuals    Download the manuals linked by the Neo Geo retail catalog.
  sync-neogeo-soundtracks  Download and index verified Neo Geo VGM packs.
  sync-mastersystem-soundtracks  Download and index verified SMS Power VGM packs.
  sync-snes-translations  Match local translation patches to verified SNES retail ROMs.
  sync-megadrive-translations  Match local translation patches to verified Mega Drive retail ROMs.
  sync-nes-translations        Match local translation patches to verified NES retail ROMs.
  sync-playstation-translations  Build translations for verified US PlayStation discs.
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
    if command == "import-integrated":
        from gamedb.integrated.__main__ import main as integrated_main

        return integrated_main(remaining)
    if command == "import-exo":
        from gamedb.exo.__main__ import main as exo_main

        return exo_main(remaining)
    if command == "import-vgm":
        from gamedb.vgm.__main__ import main as vgm_main

        return vgm_main(remaining)
    if command == "import-arcade":
        from gamedb.arcade.__main__ import main as arcade_main

        return arcade_main(remaining)
    if command == "import-rdb":
        from gamedb.rdb.__main__ import main as rdb_main

        return rdb_main(remaining)
    if command == "import-launchbox":
        from gamedb.launchbox.__main__ import main as launchbox_main

        return launchbox_main(remaining)
    if command in {
        "rebuild", "seed-snes", "seed-megadrive", "seed-nes", "seed-playstation", "seed-neogeo", "sync-snes-manuals",
        "sync-megadrive-manuals", "sync-nes-manuals", "sync-playstation-manuals", "sync-snes-translations",
        "sync-megadrive-translations", "sync-nes-translations", "sync-playstation-translations", "promote-corrections",
        "sync-neogeo-manuals", "sync-neogeo-soundtracks", "seed-mastersystem", "sync-mastersystem-manuals",
        "sync-mastersystem-soundtracks",
    }:
        from gamedb.catalog.cli import main as catalog_main

        return catalog_main([command, *remaining])
    if command == "serve":
        from gamedb.explorer.__main__ import main as explorer_main

        return explorer_main(remaining)
    raise SystemExit(f"unknown command {command!r}\n\n{HELP}")
