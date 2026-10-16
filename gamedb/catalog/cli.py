"""Standalone catalog-projection command line."""

import argparse
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
    promote = commands.add_parser("promote-corrections")
    promote.add_argument(
        "--reference",
        type=Path,
        default=DEFAULT_PIPELINE.parent / "reference/software_corrections.csv",
    )
    args = parser.parse_args(argv)

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
