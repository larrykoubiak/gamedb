"""Standalone loader command line."""

import argparse
import json
from pathlib import Path

from .archive_names.classifier import classify_tags
from .archive_names.parser import COLLECTIONS, parse_archive_name, should_ignore_archive_name
from .workflow import RebuildWorkflow, WorkflowConfig


DEFAULT_PIPELINE = Path(__file__).resolve().parents[2] / "pipeline.yml"


def _name_list(value: str) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(name.strip() for name in value.split(",")))
    if not names or any(not name for name in names):
        raise argparse.ArgumentTypeError("layers must be a comma-separated list of names")
    return names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb-loader")
    commands = parser.add_subparsers(dest="command", required=True)
    parse = commands.add_parser("parse-name")
    parse.add_argument("romset", choices=sorted(COLLECTIONS))
    parse.add_argument("archive_name")
    parse.add_argument("--classify", action="store_true")
    rebuild = commands.add_parser("rebuild")
    rebuild.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE)
    rebuild.add_argument("--plan", action="store_true")
    selection = rebuild.add_mutually_exclusive_group()
    selection.add_argument("--layers", type=_name_list)
    selection.add_argument("--from-layer")
    rebuild.add_argument("--through-layer")
    args = parser.parse_args(argv)

    if args.command == "rebuild":
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

    parsed = parse_archive_name(args.romset, args.archive_name)
    result = {
        "ignored": should_ignore_archive_name(args.romset, args.archive_name),
        "title_candidate": parsed.title_candidate,
        "extension": parsed.extension,
        "tags": parsed.tags,
        "records": [
            {
                "title_candidate": record.title_candidate,
                "tags": record.tags,
                "start": record.start,
                "end": record.end,
                "issues": list(record.issues),
            }
            for record in parsed.records
        ],
        "status": parsed.status,
        "issues": list(parsed.issues),
    }
    if args.classify:
        classifications = []
        for record in parsed.records:
            status = "review" if record.issues else "parsed"
            classified = classify_tags(
                args.romset, args.archive_name, record.tags, status
            )
            classifications.append({
                "tags": classified.tags,
                "issues": list(classified.issues),
            })
        result["record_classifications"] = classifications
        if len(classifications) == 1:
            result["tag_classifications"] = classifications[0]["tags"]
            result["tag_classification_issues"] = classifications[0]["issues"]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
