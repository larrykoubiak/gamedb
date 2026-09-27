"""Refresh core source identities and update derived parses by ID."""

from collections import Counter
import json

import psycopg

from gamedb.romvault.names import PARSER_VERSION, parse_archive_name


SOURCE_SQL = """
SELECT p.id, p.romset, p.archive_name
FROM etl.archive_name p
WHERE (%s OR p.parser_version IS DISTINCT FROM %s)
  AND EXISTS (
      SELECT 1 FROM public.archive a
      WHERE a.archive_name_id = p.id AND a.is_present
  )
"""


def sync_sources(conninfo: str = "") -> dict:
    with psycopg.connect(conninfo) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        changed = connection.execute("SELECT etl.refresh_system_mapping()").fetchone()[0]
        stats = connection.execute("SELECT * FROM etl.refresh_archives()").fetchone()
    return dict(zip(
        ("system_mappings_changed", "dats_changed", "names_added", "archives_changed", "archives_absent"),
        (changed, *stats),
    ))


def parse_archive_names(*, reparse: bool = False, conninfo: str = "") -> dict:
    statuses = Counter()
    issues = Counter()
    processed = 0
    with psycopg.connect(conninfo) as reader, psycopg.connect(conninfo) as writer:
        writer.execute("SELECT pg_advisory_xact_lock(hashtext('gamedb:archive_name_parse'))")
        writer.execute("""
            CREATE TEMP TABLE archive_name_load (
                id bigint PRIMARY KEY, title_candidate text, extension text,
                tags jsonb, parse_status text, parse_issues text[], parser_version text
            ) ON COMMIT DROP
        """)
        with reader.cursor(name="archive_names") as source:
            source.itersize = 5000
            source.execute(SOURCE_SQL, (reparse, PARSER_VERSION))
            with writer.cursor().copy("COPY archive_name_load FROM STDIN") as copy:
                for name_id, romset, archive_name in source:
                    parsed = parse_archive_name(romset, archive_name)
                    copy.write_row((
                        name_id, parsed.title_candidate, parsed.extension,
                        json.dumps(parsed.tags, ensure_ascii=False), parsed.status,
                        list(parsed.issues), PARSER_VERSION,
                    ))
                    processed += 1
                    statuses[parsed.status] += 1
                    issues.update(parsed.issues)
                    if processed % 100000 == 0:
                        print(f"Parsed {processed:,} archive names...", flush=True)

        result = writer.execute("""
            UPDATE etl.archive_name p
            SET title_candidate = new.title_candidate, extension = new.extension,
                tags = new.tags, parse_status = new.parse_status,
                parse_issues = new.parse_issues, parser_version = new.parser_version,
                parsed_at = now()
            FROM archive_name_load new
            WHERE p.id = new.id
              AND (p.title_candidate, p.extension, p.tags, p.parse_status,
                   p.parse_issues, p.parser_version)
                  IS DISTINCT FROM
                  (new.title_candidate, new.extension, new.tags, new.parse_status,
                   new.parse_issues, new.parser_version)
        """)
        changed = result.rowcount
    return {"processed": processed, "changed": changed, "statuses": dict(statuses), "issues": dict(issues)}
