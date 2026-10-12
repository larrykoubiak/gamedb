"""Small diagnostic CLI for the pure archive-name parser and classifier."""

import argparse
import json

from gamedb.archive_names.classifier import classify_tags
from gamedb.archive_names.parser import COLLECTIONS, parse_archive_name, should_ignore_archive_name


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gamedb", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    parse = commands.add_parser("parse-name", help="Inspect parsing for one archive filename.")
    parse.add_argument("romset", choices=sorted(COLLECTIONS))
    parse.add_argument("archive_name")
    parse.add_argument("--classify", action="store_true", help="Also interpret extracted tags.")
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
        record_classifications = []
        for record in parsed.records:
            status = "review" if record.issues else "parsed"
            classified = classify_tags(args.romset, args.archive_name, record.tags, status)
            record_classifications.append({
                "tags": classified.tags,
                "issues": list(classified.issues),
            })
        result["record_classifications"] = record_classifications
        if len(record_classifications) == 1:
            result["tag_classifications"] = record_classifications[0]["tags"]
            result["tag_classification_issues"] = record_classifications[0]["issues"]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
