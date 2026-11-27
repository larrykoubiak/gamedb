"""Standalone catalog-projection command line."""

import argparse
import json
from pathlib import Path

from .retail import CLASSIC_CARTRIDGE_PLATFORMS, HANDHELD_PLATFORMS, OPTICAL_RETAIL_PLATFORMS, SIXTH_GENERATION_PLATFORMS
from .workflow import RebuildWorkflow, WorkflowConfig


DEFAULT_PIPELINE = Path(__file__).resolve().parents[2] / "pipeline.yml"


def _name_list(value: str) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(name.strip() for name in value.split(",")))
    if not names or any(not name for name in names):
        raise argparse.ArgumentTypeError("layers must be a comma-separated list of names")
    return names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb-catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("rebuild")
    rebuild.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE)
    rebuild.add_argument("--plan", action="store_true")
    selection = rebuild.add_mutually_exclusive_group()
    selection.add_argument("--layers", type=_name_list)
    selection.add_argument("--from-layer")
    rebuild.add_argument("--through-layer")
    snes = commands.add_parser("seed-snes", help="Match the pinned SNES retail list against the catalog")
    snes.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    snes.add_argument("--report", type=Path, help="Write the full match report as JSON")
    snes.add_argument("--publish", action="store_true", help="Publish the curated SNES view to Explorer")
    snes.add_argument("--sources", type=Path, help="Directory of saved SNES reference indexes")
    snes.add_argument("--hash-cartridges", action="store_true", help="Read local No-Intro ZIPs to cache SHA-256 for PCB matching")
    megadrive = commands.add_parser("seed-megadrive", help="Build the Mega Drive retail catalog")
    megadrive.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    megadrive.add_argument("--report", type=Path, help="Write the full match report as JSON")
    megadrive.add_argument("--publish", action="store_true", help="Publish the Mega Drive catalog to Explorer")
    megadrive.add_argument("--sources", type=Path, help="Directory of saved Mega Drive reference indexes")
    mastersystem = commands.add_parser("seed-mastersystem", help="Build the Master System and Mark III retail catalog")
    mastersystem.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    mastersystem.add_argument("--report", type=Path, help="Write the full match report as JSON")
    mastersystem.add_argument("--publish", action="store_true", help="Publish the Master System catalog to Explorer")
    mastersystem.add_argument("--sources", type=Path, help="Directory of saved Master System reference indexes")
    pcengine = commands.add_parser("seed-pcengine", help="Build the PC Engine / TurboGrafx-16 HuCard catalog")
    pcengine.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    pcengine.add_argument("--report", type=Path, help="Write the full match report as JSON")
    pcengine.add_argument("--publish", action="store_true", help="Publish the HuCard catalog to Explorer")
    pcengine.add_argument("--sources", type=Path, help="Directory of saved PC Engine reference indexes")
    n64 = commands.add_parser("seed-n64", help="Build the Nintendo 64 Game Pak catalog")
    n64.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    n64.add_argument("--report", type=Path, help="Write the full match report as JSON")
    n64.add_argument("--publish", action="store_true", help="Publish the Nintendo 64 catalog to Explorer")
    n64.add_argument("--sources", type=Path, help="Directory of saved Nintendo 64 reference indexes")
    saturn = commands.add_parser("seed-saturn", help="Build the Sega Saturn retail disc catalog")
    saturn.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    saturn.add_argument("--report", type=Path, help="Write the full match report as JSON")
    saturn.add_argument("--publish", action="store_true", help="Publish the Sega Saturn catalog to Explorer")
    saturn.add_argument("--sources", type=Path, help="Directory of saved Sega Saturn reference indexes")
    jaguar = commands.add_parser("seed-jaguar", help="Build the Atari Jaguar retail cartridge catalog")
    jaguar.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    jaguar.add_argument("--report", type=Path, help="Write the full match report as JSON")
    jaguar.add_argument("--publish", action="store_true", help="Publish the Atari Jaguar catalog to Explorer")
    jaguar.add_argument("--sources", type=Path, help="Directory of saved Atari Jaguar reference indexes")
    optical = commands.add_parser("seed-optical", help="Build an optical retail catalog")
    optical.add_argument("platform", choices=OPTICAL_RETAIL_PLATFORMS)
    optical.add_argument("--report", type=Path, help="Write the full match report as JSON")
    optical.add_argument("--publish", action="store_true", help="Publish the catalog to Explorer")
    optical.add_argument("--sources", type=Path, help="Directory of saved platform reference indexes")
    cartridge = commands.add_parser("seed-cartridge", aliases=["seed-second-generation"],
                                    help="Build an early cartridge retail catalog")
    cartridge.add_argument("platform", choices=CLASSIC_CARTRIDGE_PLATFORMS)
    cartridge.add_argument("--report", type=Path, help="Write the full match report as JSON")
    cartridge.add_argument("--publish", action="store_true", help="Publish the catalog to Explorer")
    cartridge.add_argument("--sources", type=Path, help="Directory of saved reference indexes")
    handheld = commands.add_parser("seed-handheld", help="Build a handheld retail catalog")
    handheld.add_argument("platform", choices=HANDHELD_PLATFORMS)
    handheld.add_argument("--report", type=Path, help="Write the full match report as JSON")
    handheld.add_argument("--publish", action="store_true", help="Publish the catalog to Explorer")
    handheld.add_argument("--sources", type=Path, help="Directory of saved reference indexes")
    handheld_art = commands.add_parser("sync-handheld-artwork", help="Fill artwork gaps in published handheld catalogs")
    handheld_art.add_argument("--platform", action="append", choices=(*HANDHELD_PLATFORMS, "virtualboy"),
                              help="Limit the update to the selected platform. Repeat for multiple platforms")
    handheld_art.add_argument("--publish", action="store_true", help="Update the catalog in Explorer")
    handheld_art.add_argument("--report", type=Path, help="Write candidate catalogs into this directory")
    nes = commands.add_parser("seed-nes", help="Build the NES and Famicom retail catalog")
    nes.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    nes.add_argument("--report", type=Path, help="Write the full match report as JSON")
    nes.add_argument("--publish", action="store_true", help="Publish the NES catalog to Explorer")
    nes.add_argument("--sources", type=Path, help="Directory of saved NES reference indexes")
    playstation = commands.add_parser("seed-playstation", help="Build the US PlayStation retail catalog")
    playstation.add_argument("--report", type=Path, help="Write the full match report as JSON")
    playstation.add_argument("--publish", action="store_true", help="Publish the PlayStation catalog to Explorer")
    playstation.add_argument("--sources", type=Path, help="Directory of saved PlayStation reference indexes")
    neogeo = commands.add_parser("seed-neogeo", help="Build the Neo Geo MVS and AES retail catalog")
    neogeo.add_argument("--report", type=Path, help="Write the full match report as JSON")
    neogeo.add_argument("--publish", action="store_true", help="Publish the Neo Geo catalog to Explorer")
    manuals = commands.add_parser("sync-snes-manuals", help="Download the manuals linked by a SNES match report")
    manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-snes")
    manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    manuals.add_argument("--workers", type=int, default=8, help="Concurrent manual downloads (default: 8)")
    manuals.add_argument("--item-cache", type=Path,
                         default=DEFAULT_PIPELINE.parent / "data/media/cache/snes-retail/manual-items",
                         help="Cache for Internet Archive scan metadata")
    md_manuals = commands.add_parser("sync-megadrive-manuals", help="Download the linked Mega Drive manuals")
    md_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-megadrive")
    md_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    md_manuals.add_argument("--workers", type=int, default=4, help="Concurrent downloads (default: 4)")
    sms_manuals = commands.add_parser("sync-mastersystem-manuals", help="Download the linked Master System manuals")
    sms_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-mastersystem")
    sms_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    sms_manuals.add_argument("--workers", type=int, default=4, help="Concurrent downloads (default: 4)")
    pce_manuals = commands.add_parser("sync-pcengine-manuals", help="Download the linked HuCard manuals")
    pce_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-pcengine")
    pce_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    pce_manuals.add_argument("--workers", type=int, default=6, help="Concurrent downloads (default: 6)")
    n64_manuals = commands.add_parser("sync-n64-manuals", help="Download the linked Nintendo 64 manuals")
    n64_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-n64")
    n64_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    n64_manuals.add_argument("--workers", type=int, default=8, help="Concurrent downloads (default: 8)")
    saturn_manuals = commands.add_parser("sync-saturn-manuals", help="Download the linked Saturn manuals")
    saturn_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-saturn")
    saturn_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    saturn_manuals.add_argument("--workers", type=int, default=8, help="Concurrent downloads (default: 8)")
    jaguar_manuals = commands.add_parser("sync-jaguar-manuals", help="Download the linked Jaguar manuals")
    jaguar_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-jaguar")
    jaguar_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    jaguar_manuals.add_argument("--workers", type=int, default=8, help="Concurrent downloads (default: 8)")
    cartridge_manuals = commands.add_parser("sync-cartridge-manuals", aliases=["sync-second-generation-manuals"],
                                           help="Mirror the manuals linked by an early cartridge catalog")
    cartridge_manuals.add_argument("platform", choices=CLASSIC_CARTRIDGE_PLATFORMS)
    cartridge_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-cartridge")
    cartridge_manuals.add_argument("--root", type=Path, help="Local directory for this platform's manual library")
    cartridge_manuals.add_argument("--workers", type=int, default=4, help="Concurrent manual downloads")
    optical_manuals = commands.add_parser("sync-optical-manuals", help="Download manuals linked by an optical retail catalog")
    optical_manuals.add_argument("platform", choices=OPTICAL_RETAIL_PLATFORMS)
    optical_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-optical")
    handheld_manuals = commands.add_parser("sync-handheld-manuals", help="Mirror manuals linked by a handheld catalog")
    handheld_manuals.add_argument("platform", choices=HANDHELD_PLATFORMS)
    handheld_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-handheld")
    handheld_manuals.add_argument("--root", type=Path, help="Local directory for this platform's manual library")
    handheld_manuals.add_argument("--workers", type=int, default=4, help="Concurrent downloads")
    optical_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    optical_manuals.add_argument("--workers", type=int, default=8, help="Concurrent downloads (default: 8)")
    nes_manuals = commands.add_parser("sync-nes-manuals", help="Download the linked NES and Famicom manuals")
    nes_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-nes")
    nes_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    nes_manuals.add_argument("--workers", type=int, default=6, help="Concurrent downloads (default: 6)")
    ps_manuals = commands.add_parser("sync-playstation-manuals", help="Download the linked US PlayStation manuals")
    ps_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-playstation")
    ps_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    ps_manuals.add_argument("--workers", type=int, default=4, help="Concurrent downloads (default: 4)")
    ng_manuals = commands.add_parser("sync-neogeo-manuals", help="Download the linked Neo Geo manuals")
    ng_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-neogeo")
    ng_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    ng_manuals.add_argument("--workers", type=int, default=6, help="Concurrent manual downloads")
    ng_music = commands.add_parser("sync-neogeo-soundtracks", help="Mirror and index verified Neo Geo VGM packs")
    ng_music.add_argument("--root", type=Path, help="VGM library root")
    ng_music.add_argument("--workers", type=int, default=4, help="Concurrent soundtrack downloads")
    sms_music = commands.add_parser("sync-mastersystem-soundtracks", help="Mirror and index reviewed SMS Power VGM packs")
    sms_music.add_argument("--root", type=Path, help="VGM library root")
    sms_music.add_argument("--workers", type=int, default=4, help="Concurrent soundtrack downloads")
    cartridge_music = commands.add_parser("sync-cartridge-soundtracks", aliases=["sync-second-generation-soundtracks"],
                                         help="Mirror and index reviewed early-console VGM packs")
    cartridge_music.add_argument("--root", type=Path, help="VGM library root")
    translations = commands.add_parser("sync-snes-translations", help="Match RHDN patches to verified SNES retail ROMs")
    translations.add_argument("--source", required=True, type=Path, help="Local RHDN backup directory")
    translations.add_argument("--root", type=Path, help="Local patch library (default: data/media/snes-translations)")
    md_translations = commands.add_parser("sync-megadrive-translations", help="Match RHDN patches to verified Mega Drive cartridges")
    md_translations.add_argument("--source", required=True, type=Path, help="RHDN backup root or translations/genesis directory")
    md_translations.add_argument("--root", type=Path, help="Local patch library (default: data/media/megadrive-translations)")
    md_translations.add_argument("--report", type=Path, help="Write an audit of packages that could not be matched")
    nes_translations = commands.add_parser("sync-nes-translations", help="Match RHDN patches to verified NES cartridges")
    nes_translations.add_argument("--source", required=True, type=Path, help="RHDN backup root or translations/nes directory")
    nes_translations.add_argument("--root", type=Path, help="Local patch library (default: data/media/nes-translations)")
    nes_translations.add_argument("--report", type=Path, help="Write an audit of packages that could not be matched")
    ps_translations = commands.add_parser("sync-playstation-translations", help="Build reviewed US PlayStation translations")
    ps_translations.add_argument("--source", required=True, type=Path, help="RHDN backup root or translations/psx directory")
    ps_translations.add_argument("--root", type=Path, help="Local patch and disc library (default: data/media/playstation-translations)")
    ps_translations.add_argument("--report", type=Path, help="Write the list of verified builds and failures")
    translation_commands = {"snes": translations, "megadrive": md_translations, "nes": nes_translations,
                            "playstation": ps_translations}
    from .translations import HANDHELD_PATCH_SOURCES

    handheld_patches = commands.add_parser("sync-handheld-translations", help="Verify and index handheld translation patches")
    handheld_patches.add_argument("platform", choices=HANDHELD_PATCH_SOURCES)
    handheld_patches.add_argument("--source", type=Path, required=True, help="Local RHDN backup directory")
    handheld_patches.add_argument("--root", type=Path, help="Local patch library for this platform")
    handheld_patches.add_argument("--report", type=Path, help="Write an audit of packages that could not be matched")
    for platform, label in (("mastersystem", "Master System ROMs"), ("pcengine", "HuCards"),
                            ("n64", "Nintendo 64 Game Paks"), ("saturn", "Saturn discs"),
                            ("pcfx", "PC-FX discs"), ("3do", "3DO discs"),
                            ("segacd", "Sega CD discs"), ("pcecd", "PC Engine CD discs"),
                            ("neogeocd", "Neo Geo CD discs"), ("colecovision", "ColecoVision cartridges"),
                            *SIXTH_GENERATION_PLATFORMS.items()):
        command = commands.add_parser(f"sync-{platform}-translations", help=f"Match patches to verified {label}")
        command.add_argument("--source", type=Path, required=True, help="Local RHDN backup directory")
        command.add_argument("--root", type=Path, help=f"Local patch library (default: data/media/{platform}-translations)")
        command.add_argument("--report", type=Path, help="Write an audit of packages that could not be matched")
        translation_commands[platform] = command
    ng_translations = commands.add_parser("sync-neogeo-translations", help="Index reviewed NeoSD patches for Neo Geo cartridges")
    ng_translations.add_argument("--source", type=Path, required=True, help="Directory of the original patch downloads")
    ng_translations.add_argument("--root", type=Path, help="Local patch library (default: data/media/neogeo-translations)")
    ng_translations.add_argument("--report", type=Path, help="Write the set and patch counts")
    promote = commands.add_parser("promote-corrections")
    promote.add_argument(
        "--reference",
        type=Path,
        default=DEFAULT_PIPELINE.parent / "reference/software_corrections.csv",
    )
    args = parser.parse_args(argv)

    if args.command == "seed-snes":
        from .snes import seed_snes

        try:
            result = seed_snes(args.html, args.report, publish_catalog=args.publish, sources=args.sources,
                               hash_cartridges=args.hash_cartridges)
        except (OSError, ValueError) as error:
            snes.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "seed-playstation":
        from .playstation import seed_playstation

        try:
            result = seed_playstation(args.report, publish_catalog=args.publish, sources=args.sources)
        except (OSError, ValueError) as error:
            playstation.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "seed-neogeo":
        from .neogeo import seed_neogeo

        try:
            result = seed_neogeo(args.report, publish_catalog=args.publish)
        except (OSError, ValueError) as error:
            neogeo.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command in {"sync-neogeo-soundtracks", "sync-mastersystem-soundtracks"}:
        if args.command == "sync-mastersystem-soundtracks":
            from .mastersystem_music import sync_soundtracks

            command = sms_music
        else:
            from .neogeo_music import sync_soundtracks

            command = ng_music

        try:
            result = sync_soundtracks(args.root, workers=args.workers)
        except (OSError, ValueError) as error:
            command.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result["failures"]))

    if args.command in {"sync-cartridge-soundtracks", "sync-second-generation-soundtracks"}:
        from .second_generation_music import sync_soundtracks

        try:
            result = sync_soundtracks(args.root)
        except (OSError, ValueError) as error:
            cartridge_music.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "seed-optical":
        from .early_disc import seed

        try:
            result = seed(args.platform, args.report, publish_catalog=args.publish, sources=args.sources)
        except (OSError, ValueError) as error:
            optical.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "seed-handheld":
        from .handhelds import seed_handheld

        try:
            result = seed_handheld(args.platform, args.report, publish_catalog=args.publish, sources=args.sources)
        except (OSError, ValueError) as error:
            handheld.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "sync-handheld-artwork":
        from .handheld_artwork import PLATFORMS, refresh_handheld_artwork

        try:
            platforms = tuple(dict.fromkeys(args.platform)) if args.platform else PLATFORMS
            result = refresh_handheld_artwork(platforms, publish=args.publish, report=args.report)
        except (OSError, ValueError) as error:
            handheld_art.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "sync-handheld-translations":
        from .translations import TRANSLATION_ROOTS, sync_translations

        try:
            result = sync_translations(args.source, args.root or TRANSLATION_ROOTS[args.platform],
                                       platform=args.platform, report=args.report)
        except (OSError, ValueError) as error:
            handheld_patches.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command in {"seed-cartridge", "seed-second-generation"}:
        from .second_generation import seed_cartridge

        try:
            result = seed_cartridge(args.platform, args.report, publish_catalog=args.publish, sources=args.sources)
        except (OSError, ValueError) as error:
            cartridge.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command in {"seed-megadrive", "seed-mastersystem", "seed-pcengine", "seed-nes", "seed-n64", "seed-saturn",
                        "seed-jaguar"}:
        if args.command == "seed-nes":
            from .nes import seed_nes as seed

            command = nes
        elif args.command == "seed-mastersystem":
            from .mastersystem import seed_mastersystem as seed

            command = mastersystem
        elif args.command == "seed-pcengine":
            from .pcengine import seed_pcengine as seed

            command = pcengine
        elif args.command == "seed-n64":
            from .n64 import seed_n64 as seed

            command = n64
        elif args.command == "seed-saturn":
            from .saturn import seed_saturn as seed

            command = saturn
        elif args.command == "seed-jaguar":
            from .jaguar import seed_jaguar as seed

            command = jaguar
        else:
            from .megadrive import seed_megadrive as seed

            command = megadrive

        try:
            result = seed(args.html, args.report, publish_catalog=args.publish, sources=args.sources)
        except (OSError, ValueError) as error:
            command.error(str(error))
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "sync-snes-manuals":
        from .manuals import sync_manuals

        try:
            result = sync_manuals(args.catalog, args.root, args.item_cache, workers=args.workers)
        except (OSError, ValueError) as error:
            manuals.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result["failures"]))

    if args.command == "sync-optical-manuals":
        from .early_disc import SOURCE_DIRECTORY
        from .manuals import sync_manuals

        try:
            result = sync_manuals(args.catalog, args.root, SOURCE_DIRECTORY / args.platform / "manual-items",
                                  workers=args.workers, source_references=None)
        except (OSError, ValueError) as error:
            optical_manuals.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result["failures"]))

    if args.command == "sync-handheld-manuals":
        from gamedb.explorer.manuals import manual_roots

        from .handhelds import SOURCE_DIRECTORY
        from .manuals import sync_manuals

        try:
            result = sync_manuals(args.catalog, args.root or manual_roots()[args.platform],
                                  SOURCE_DIRECTORY / "manual-items", workers=args.workers, source_references=None)
        except (OSError, ValueError) as error:
            handheld_manuals.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result["failures"]))

    if args.command in {"sync-cartridge-manuals", "sync-second-generation-manuals"}:
        from gamedb.explorer.manuals import manual_roots

        from .manuals import sync_manuals
        from .second_generation import SOURCE_DIRECTORY

        try:
            result = sync_manuals(args.catalog, args.root or manual_roots()[args.platform],
                                  SOURCE_DIRECTORY / "manual-items", workers=args.workers, source_references=None)
        except (OSError, ValueError) as error:
            cartridge_manuals.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result["failures"]))

    if args.command in {"sync-megadrive-manuals", "sync-mastersystem-manuals", "sync-pcengine-manuals", "sync-nes-manuals",
                        "sync-playstation-manuals", "sync-neogeo-manuals", "sync-n64-manuals", "sync-saturn-manuals",
                        "sync-jaguar-manuals"}:
        from .manuals import sync_manuals

        if args.command == "sync-nes-manuals":
            from .nes import SOURCE_DIRECTORY

            command = nes_manuals
        elif args.command == "sync-mastersystem-manuals":
            from .mastersystem import SOURCE_DIRECTORY

            command = sms_manuals
        elif args.command == "sync-pcengine-manuals":
            from .pcengine import SOURCE_DIRECTORY

            command = pce_manuals
        elif args.command == "sync-n64-manuals":
            from .n64 import SOURCE_DIRECTORY

            command = n64_manuals
        elif args.command == "sync-saturn-manuals":
            from .saturn import SOURCE_DIRECTORY

            command = saturn_manuals
        elif args.command == "sync-jaguar-manuals":
            from .jaguar import SOURCE_DIRECTORY

            command = jaguar_manuals
        elif args.command == "sync-playstation-manuals":
            from .playstation import SOURCE_DIRECTORY

            command = ps_manuals
        elif args.command == "sync-neogeo-manuals":
            from .neogeo import SOURCE_DIRECTORY

            command = ng_manuals
        else:
            from .megadrive import SOURCE_DIRECTORY

            command = md_manuals

        try:
            result = sync_manuals(args.catalog, args.root, SOURCE_DIRECTORY / "manual-items", workers=args.workers,
                                  source_references=None)
        except (OSError, ValueError) as error:
            command.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result["failures"]))

    if args.command in {f"sync-{name}-translations" for name in translation_commands}:
        from .translations import TRANSLATION_ROOTS, sync_translations

        platform = args.command.split("-")[1]
        command = translation_commands[platform]
        try:
            result = sync_translations(args.source, args.root or TRANSLATION_ROOTS[platform],
                                       platform=platform, report=getattr(args, "report", None))
        except (OSError, ValueError) as error:
            command.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result.get("failures")))

    if args.command == "sync-neogeo-translations":
        from .neogeo_translations import sync_neogeo_translations
        from .translations import TRANSLATION_ROOTS

        try:
            result = sync_neogeo_translations(args.source, args.root or TRANSLATION_ROOTS["neogeo"], report=args.report)
        except (OSError, ValueError) as error:
            ng_translations.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "promote-corrections":
        from gamedb.database import create_database_engine

        from .corrections import SoftwareCorrectionPromoter

        count = SoftwareCorrectionPromoter(
            create_database_engine(), args.reference.resolve()
        ).execute()
        print(f"Promoted {count} software correction(s).")
        return 0

    try:
        config = WorkflowConfig.load(args.pipeline).select(
            layers=args.layers or (),
            from_layer=args.from_layer,
            through_layer=args.through_layer,
        )
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    workflow = RebuildWorkflow(config)
    print(workflow.describe()) if args.plan else workflow.execute()
    return 0
