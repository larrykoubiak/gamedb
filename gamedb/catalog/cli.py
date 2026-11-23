"""Standalone catalog-projection command line."""

import argparse
import json
from pathlib import Path

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
    nes = commands.add_parser("seed-nes", help="Build the NES and Famicom retail catalog")
    nes.add_argument("--html", type=Path, help="Use a saved copy of the pinned Wikipedia HTML")
    nes.add_argument("--report", type=Path, help="Write the full match report as JSON")
    nes.add_argument("--publish", action="store_true", help="Publish the NES catalog to Explorer")
    nes.add_argument("--sources", type=Path, help="Directory of saved NES reference indexes")
    playstation = commands.add_parser("seed-playstation", help="Build the US PlayStation retail catalog")
    playstation.add_argument("--report", type=Path, help="Write the full match report as JSON")
    playstation.add_argument("--publish", action="store_true", help="Publish the PlayStation catalog to Explorer")
    playstation.add_argument("--sources", type=Path, help="Directory of saved PlayStation reference indexes")
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
    nes_manuals = commands.add_parser("sync-nes-manuals", help="Download the linked NES and Famicom manuals")
    nes_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-nes")
    nes_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    nes_manuals.add_argument("--workers", type=int, default=6, help="Concurrent downloads (default: 6)")
    ps_manuals = commands.add_parser("sync-playstation-manuals", help="Download the linked US PlayStation manuals")
    ps_manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-playstation")
    ps_manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    ps_manuals.add_argument("--workers", type=int, default=4, help="Concurrent downloads (default: 4)")
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

    if args.command in {"seed-megadrive", "seed-nes"}:
        if args.command == "seed-nes":
            from .nes import seed_nes as seed

            command = nes
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

    if args.command in {"sync-megadrive-manuals", "sync-nes-manuals", "sync-playstation-manuals"}:
        from .manuals import sync_manuals

        if args.command == "sync-nes-manuals":
            from .nes import SOURCE_DIRECTORY

            command = nes_manuals
        elif args.command == "sync-playstation-manuals":
            from .playstation import SOURCE_DIRECTORY

            command = ps_manuals
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

    if args.command in {"sync-snes-translations", "sync-megadrive-translations", "sync-nes-translations"}:
        from .translations import TRANSLATION_ROOTS, sync_translations

        platform = args.command.split("-")[1]
        command = {"snes": translations, "megadrive": md_translations, "nes": nes_translations}[platform]
        try:
            result = sync_translations(args.source, args.root or TRANSLATION_ROOTS[platform],
                                       platform=platform, report=getattr(args, "report", None))
        except (OSError, ValueError) as error:
            command.error(str(error))
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
