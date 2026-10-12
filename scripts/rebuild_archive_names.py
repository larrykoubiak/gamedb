#!/usr/bin/env python3
"""Parse staged archive names and bulk-load the derived relational tables."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from gamedb.archive_names.classifier import CLASSIFIER_VERSION, classify_tags  # noqa: E402
from gamedb.archive_names.parser import (  # noqa: E402
    PARSER_VERSION,
    parse_archive_name,
    should_ignore_archive_name,
)


SOURCE_SQL = r"""
COPY (
    SELECT DISTINCT d.romset, rf.game_display_name AS archive_name
    FROM staging.rv_files rf
    JOIN derived.dat d
      ON d.dat_path = rf.dat_root_full_name
     AND d.dat_name = rf.dat_name
    WHERE nullif(btrim(rf.game_display_name), '') IS NOT NULL
    ORDER BY d.romset, rf.game_display_name
) TO STDOUT WITH (FORMAT csv)
"""


def _writer(path: Path, header: list[str]):
    handle = path.open("w", encoding="utf-8", newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(header)
    return handle, writer


def _parse_to_csv(directory: Path) -> tuple[dict[str, Path], dict[str, int]]:
    paths = {
        "archive_names": directory / "archive_names.csv",
        "records": directory / "archive_name_records.csv",
        "tags": directory / "archive_tags.csv",
    }
    name_handle, names = _writer(paths["archive_names"], [
        "romset", "archive_name", "extension", "parse_status", "parse_issues", "parser_version",
    ])
    record_handle, records = _writer(paths["records"], [
        "romset", "archive_name", "record_index", "title_candidate", "source_start", "source_end",
        "parse_status", "parse_issues", "classification_issues", "classifier_version",
    ])
    tag_handle, tags = _writer(paths["tags"], [
        "romset", "archive_name", "record_index", "tag_index", "raw_value", "identifier",
        "value", "delimiter", "source_start", "source_end", "category",
        "classification_status", "rule", "details",
    ])
    counts = {"archive_names": 0, "records": 0, "tags": 0, "ignored": 0}

    process = subprocess.Popen(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atq", "-c", SOURCE_SQL],
        cwd=REPOSITORY,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    try:
        for romset, archive_name in csv.reader(process.stdout):
            if should_ignore_archive_name(romset, archive_name):
                counts["ignored"] += 1
                continue
            parsed = parse_archive_name(romset, archive_name)
            names.writerow([
                romset, archive_name, parsed.extension, parsed.status,
                json.dumps(parsed.issues), PARSER_VERSION,
            ])
            counts["archive_names"] += 1

            for record_index, record in enumerate(parsed.records, 1):
                parse_status = "review" if record.issues else "parsed"
                classified = classify_tags(
                    romset, archive_name, record.tags, parse_status,
                )
                records.writerow([
                    romset, archive_name, record_index, record.title_candidate,
                    record.start, record.end, parse_status,
                    json.dumps(record.issues), json.dumps(classified.issues),
                    CLASSIFIER_VERSION,
                ])
                counts["records"] += 1

                for tag_index, (tag, classification) in enumerate(
                    zip(record.tags, classified.tags), 1
                ):
                    tags.writerow([
                        romset, archive_name, record_index, tag_index,
                        tag["value"], classification["identifier"], classification["value"],
                        tag["delimiter"], tag["start"], tag["end"],
                        classification["category"], classification["status"],
                        classification["rule"],
                        json.dumps(classification["details"], ensure_ascii=False),
                    ])
                    counts["tags"] += 1
    finally:
        process.stdout.close()
        name_handle.close()
        record_handle.close()
        tag_handle.close()

    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, process.args)
    return paths, counts


def _load_csv(paths: dict[str, Path]) -> None:
    sql = (REPOSITORY / "sql" / "rebuild" / "002_archive_names.sql").read_text()
    replacements = {
        "__ARCHIVE_NAMES_CSV__": paths["archive_names"],
        "__ARCHIVE_NAME_RECORDS_CSV__": paths["records"],
        "__ARCHIVE_TAGS_CSV__": paths["tags"],
    }
    for placeholder, path in replacements.items():
        value = str(path)
        if "'" in value or "\n" in value:
            raise ValueError(f"unsafe temporary path: {value!r}")
        sql = sql.replace(placeholder, value)
    subprocess.run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=REPOSITORY,
        input=sql,
        text=True,
        check=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="gamedb-archive-names-") as temporary:
        paths, counts = _parse_to_csv(Path(temporary))
        print(
            "Parsed "
            f"{counts['archive_names']:,} names, {counts['records']:,} records, "
            f"and {counts['tags']:,} tags; ignored {counts['ignored']:,} names by policy.",
            flush=True,
        )
        _load_csv(paths)
    print("Rebuilt derived archive-name tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
