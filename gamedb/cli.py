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
  seed-pcengine  Build the PC Engine / TurboGrafx-16 HuCard catalog.
  seed-n64  Build the Nintendo 64 Game Pak catalog.
  seed-saturn  Build the Sega Saturn retail disc catalog.
  seed-jaguar  Build the Atari Jaguar retail cartridge catalog.
  seed-optical  Build an optical retail catalog, including the sixth-generation consoles.
  seed-cartridge  Build an early cartridge retail catalog.
  seed-handheld  Build a handheld retail catalog.
  seed-nes        Build the NES and Famicom retail catalog.
  seed-playstation  Build the US PlayStation retail catalog.
  seed-neogeo     Build the Neo Geo MVS and AES retail catalog.
  sync-snes-manuals  Download the manuals linked by the SNES retail catalog.
  sync-megadrive-manuals  Download the manuals linked by the Mega Drive retail catalog.
  sync-mastersystem-manuals  Download the manuals linked by the Master System retail catalog.
  sync-pcengine-manuals  Download the manuals linked by the HuCard catalog.
  sync-n64-manuals  Download the manuals linked by the Nintendo 64 catalog.
  sync-saturn-manuals  Download the manuals linked by the Sega Saturn catalog.
  sync-jaguar-manuals  Download the manuals linked by the Atari Jaguar catalog.
  sync-optical-manuals  Download the manuals linked by an optical retail catalog.
  sync-cartridge-manuals  Mirror the manuals linked by an early cartridge catalog.
  sync-handheld-manuals  Mirror the manuals linked by a handheld catalog.
  sync-handheld-artwork  Fill artwork gaps in published handheld catalogs.
  sync-handheld-translations  Verify and index handheld translation patches.
  sync-nes-manuals       Download the manuals linked by the NES and Famicom retail catalog.
  sync-playstation-manuals  Download the manuals linked by the PlayStation retail catalog.
  sync-neogeo-manuals    Download the manuals linked by the Neo Geo retail catalog.
  sync-neogeo-soundtracks  Download and index verified Neo Geo VGM packs.
  sync-mastersystem-soundtracks  Download and index verified SMS Power VGM packs.
  sync-cartridge-soundtracks  Download and index reviewed VGM packs for early consoles.
  sync-snes-translations  Match local translation patches to verified SNES retail ROMs.
  sync-megadrive-translations  Match local translation patches to verified Mega Drive retail ROMs.
  sync-nes-translations        Match local translation patches to verified NES retail ROMs.
  sync-mastersystem-translations  Match local translation patches to verified Master System ROMs.
  sync-pcengine-translations  Match local translation patches to verified HuCards.
  sync-n64-translations  Match local translation patches to verified Nintendo 64 Game Paks.
  sync-saturn-translations  Match local translation patches to verified Sega Saturn discs.
  sync-pcfx-translations  Match local translation patches to verified PC-FX discs.
  sync-3do-translations  Match local translation patches to verified 3DO discs.
  sync-dreamcast-translations  Match reviewed Dreamcast translation patches.
  sync-playstation2-translations  Match reviewed US PlayStation 2 translation patches.
  sync-gamecube-translations  Match reviewed US GameCube translation patches.
  sync-segacd-translations  Match reviewed Sega CD translation patches.
  sync-pcecd-translations   Match reviewed PC Engine CD translation patches.
  sync-neogeocd-translations  Match reviewed Neo Geo CD translation patches.
  sync-colecovision-translations  Match local translation patches to verified ColecoVision cartridges.
  sync-neogeo-translations  Index reviewed NeoSD patches for Neo Geo cartridges.
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
        "sync-mastersystem-soundtracks", "seed-pcengine", "sync-pcengine-manuals",
        "sync-mastersystem-translations", "sync-pcengine-translations", "sync-neogeo-translations",
        "seed-n64", "sync-n64-manuals", "sync-n64-translations",
        "seed-saturn", "sync-saturn-manuals", "sync-saturn-translations",
        "seed-jaguar", "sync-jaguar-manuals", "seed-optical", "sync-optical-manuals",
        "sync-pcfx-translations", "sync-3do-translations", "sync-segacd-translations",
        "sync-pcecd-translations", "sync-neogeocd-translations", "sync-colecovision-translations",
        "sync-dreamcast-translations", "sync-playstation2-translations", "sync-gamecube-translations",
        "seed-cartridge", "sync-cartridge-manuals", "sync-cartridge-soundtracks",
        "seed-handheld", "sync-handheld-artwork", "sync-handheld-manuals", "sync-handheld-translations",
        "seed-second-generation", "sync-second-generation-manuals", "sync-second-generation-soundtracks",
    }:
        from gamedb.catalog.cli import main as catalog_main

        return catalog_main([command, *remaining])
    if command == "serve":
        from gamedb.explorer.__main__ import main as explorer_main

        return explorer_main(remaining)
    raise SystemExit(f"unknown command {command!r}\n\n{HELP}")
