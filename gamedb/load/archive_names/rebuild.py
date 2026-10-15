"""Parse staged archive names and bulk-load the derived relational tables."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Iterator

from .classifier import CLASSIFIER_VERSION, classify_tags
from .parser import PARSER_VERSION, parse_archive_name, should_ignore_archive_name


REPOSITORY = Path(__file__).resolve().parents[3]

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


class ArchiveNameSource:
    """Stream distinct staged archive names without holding them in memory."""

    def __init__(self, repository: Path = REPOSITORY):
        self.repository = repository
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> Iterator[tuple[str, str]]:
        self.process = subprocess.Popen(
            ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atq", "-c", SOURCE_SQL],
            cwd=self.repository,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert self.process.stdout is not None
        return iter(csv.reader(self.process.stdout))

    def __exit__(self, exception_type, exception, traceback) -> None:
        assert self.process is not None and self.process.stdout is not None
        self.process.stdout.close()
        return_code = self.process.wait()
        if exception_type is None and return_code:
            raise subprocess.CalledProcessError(return_code, self.process.args)


class ArchiveNameCsvWriter:
    """Serialize parsed names, records, and tags for PostgreSQL COPY."""

    HEADERS = {
        "archive_names": [
            "romset", "archive_name", "extension", "parse_status",
            "parse_issues", "parser_version",
        ],
        "records": [
            "romset", "archive_name", "record_index", "title_candidate",
            "source_start", "source_end", "parse_status", "parse_issues",
            "classification_issues", "classifier_version",
        ],
        "tags": [
            "romset", "archive_name", "record_index", "tag_index", "raw_value",
            "identifier", "value", "delimiter", "source_start", "source_end",
            "category", "classification_status", "rule", "details",
        ],
    }

    def __init__(self, directory: Path):
        self.paths = {
            "archive_names": directory / "archive_names.csv",
            "records": directory / "archive_name_records.csv",
            "tags": directory / "archive_tags.csv",
        }
        self.handles = []
        self.writers: dict[str, object] = {}
        self.counts = {"archive_names": 0, "records": 0, "tags": 0, "ignored": 0}

    def __enter__(self) -> ArchiveNameCsvWriter:
        for name, path in self.paths.items():
            handle = path.open("w", encoding="utf-8", newline="")
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(self.HEADERS[name])
            self.handles.append(handle)
            self.writers[name] = writer
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        for handle in self.handles:
            handle.close()

    def ignore(self) -> None:
        self.counts["ignored"] += 1

    def write(self, romset: str, archive_name: str) -> None:
        parsed = parse_archive_name(romset, archive_name)
        self.writers["archive_names"].writerow([
            romset, archive_name, parsed.extension, parsed.status,
            json.dumps(parsed.issues), PARSER_VERSION,
        ])
        self.counts["archive_names"] += 1

        for record_index, record in enumerate(parsed.records, 1):
            parse_status = "review" if record.issues else "parsed"
            classified = classify_tags(romset, archive_name, record.tags, parse_status)
            self.writers["records"].writerow([
                romset, archive_name, record_index, record.title_candidate,
                record.start, record.end, parse_status, json.dumps(record.issues),
                json.dumps(classified.issues), CLASSIFIER_VERSION,
            ])
            self.counts["records"] += 1

            for tag_index, (tag, classification) in enumerate(
                zip(record.tags, classified.tags), 1
            ):
                self.writers["tags"].writerow([
                    romset, archive_name, record_index, tag_index, tag["value"],
                    classification["identifier"], classification["value"],
                    tag["delimiter"], tag["start"], tag["end"],
                    classification["category"], classification["status"],
                    classification["rule"],
                    json.dumps(classification["details"], ensure_ascii=False),
                ])
                self.counts["tags"] += 1


class ArchiveNameLoader:
    """Load generated CSVs using the independently inspectable SQL script."""

    PLACEHOLDERS = {
        "__ARCHIVE_NAMES_CSV__": "archive_names",
        "__ARCHIVE_NAME_RECORDS_CSV__": "records",
        "__ARCHIVE_TAGS_CSV__": "tags",
    }

    def __init__(self, load_file: Path, repository: Path = REPOSITORY):
        self.load_file = load_file
        self.repository = repository

    def load(self, paths: dict[str, Path]) -> None:
        sql = self.load_file.read_text(encoding="utf-8")
        for placeholder, name in self.PLACEHOLDERS.items():
            value = str(paths[name])
            if "'" in value or "\n" in value:
                raise ValueError(f"unsafe temporary path: {value!r}")
            sql = sql.replace(placeholder, value)
        subprocess.run(
            ["psql", "-X", "-v", "ON_ERROR_STOP=1"],
            cwd=self.repository,
            input=sql,
            text=True,
            check=True,
        )


class ArchiveNameRebuilder:
    """Coordinate source streaming, parsing/classification, and bulk loading."""

    def __init__(self, load_file: Path, repository: Path = REPOSITORY):
        self.source = ArchiveNameSource(repository)
        self.loader = ArchiveNameLoader(load_file, repository)

    def execute(self) -> dict[str, int]:
        with tempfile.TemporaryDirectory(prefix="gamedb-archive-names-") as temporary:
            with self.source as names, ArchiveNameCsvWriter(Path(temporary)) as output:
                for romset, archive_name in names:
                    if should_ignore_archive_name(romset, archive_name):
                        output.ignore()
                    else:
                        output.write(romset, archive_name)
            counts = output.counts.copy()
            self.loader.load(output.paths)
        return counts


def main(argv=None) -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument(
        "--load-file",
        type=Path,
        default=REPOSITORY / "sql" / "layers" / "archive_names" / "010_load.sql",
        help="SQL loader for the generated CSV files.",
    )
    args = arguments.parse_args(argv)
    load_file = args.load_file.resolve()
    if not load_file.is_file():
        arguments.error(f"load SQL file not found: {load_file}")

    counts = ArchiveNameRebuilder(load_file).execute()
    print(
        "Parsed "
        f"{counts['archive_names']:,} names, {counts['records']:,} records, "
        f"and {counts['tags']:,} tags; ignored {counts['ignored']:,} names by policy."
    )
    print("Rebuilt derived archive-name tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
