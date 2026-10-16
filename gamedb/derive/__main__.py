"""Command line for the standalone derivation owner."""

from __future__ import annotations

import argparse
import json

from gamedb.database import create_database_engine

from .pipeline import DerivationPipeline


def _layer_list(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb-derive")
    parser.add_argument("--plan", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--rebuild",
        action="store_true",
        help="recreate all derived data and invalidate the catalog projection",
    )
    selection.add_argument("--layers", type=_layer_list, default=())
    selection.add_argument("--from-layer")
    args = parser.parse_args(argv)

    if not (args.rebuild or args.layers or args.from_layer or args.plan):
        parser.error(
            "choose --rebuild, --layers, or --from-layer; derivation does "
            "not rebuild implicitly"
        )

    # Planning is a manifest-only operation and must not require a database
    # driver or connection settings.
    pipeline = DerivationPipeline(None if args.plan else create_database_engine())
    try:
        if args.rebuild:
            layers = pipeline.select()
        elif args.layers or args.from_layer:
            layers = pipeline.select(args.layers, args.from_layer)
            if layers and layers[0].name == "schema":
                parser.error("the schema layer may only be run with --rebuild")
        elif args.plan:
            layers = pipeline.select()
    except ValueError as error:
        parser.error(str(error))
    if args.plan:
        print(pipeline.describe(layers))
    else:
        pipeline.execute(layers)
    return 0


def parse_name_main(argv=None) -> int:
    """Inspect one source name using the deriver's production rules."""
    from .parser.classifier import classify_tags
    from .parser.config import COLLECTIONS
    from .parser.structure import parse_archive_name, should_ignore_archive_name

    parser = argparse.ArgumentParser(prog="gamedb parse-name")
    parser.add_argument(
        "romset",
        choices=sorted(COLLECTIONS),
    )
    parser.add_argument("archive_name")
    parser.add_argument("--classify", action="store_true")
    args = parser.parse_args(argv)
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
            classified = classify_tags(args.romset, args.archive_name, record.tags, status)
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


if __name__ == "__main__":
    raise SystemExit(main())
