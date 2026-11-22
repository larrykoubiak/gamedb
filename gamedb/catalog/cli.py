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
    manuals = commands.add_parser("sync-snes-manuals", help="Download the manuals linked by a SNES match report")
    manuals.add_argument("--catalog", required=True, type=Path, help="JSON report from seed-snes")
    manuals.add_argument("--root", required=True, type=Path, help="Local directory for the manual library")
    manuals.add_argument("--workers", type=int, default=8, help="Concurrent manual downloads (default: 8)")
    manuals.add_argument("--item-cache", type=Path,
                         default=DEFAULT_PIPELINE.parent / "data/media/cache/snes-retail/manual-items",
                         help="Cache for Internet Archive scan metadata")
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

    if args.command == "sync-snes-manuals":
        from .snes_manuals import sync_manuals

        try:
            result = sync_manuals(args.catalog, args.root, args.item_cache, workers=args.workers)
        except (OSError, ValueError) as error:
            manuals.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(result["failures"]))

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
