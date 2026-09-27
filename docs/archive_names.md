# Archive name extraction

`etl.archive_name` stores the first parsing pass over ZIP names from
`staging.rv_files.game_display_name`. Individual member names such as
`track07.raw` or `readme.txt` are not title inputs.

Each row has a stable `id`, a collection (`romset`), the unchanged `archive_name`, a
`title_candidate`, the ZIP extension, ordered `tags`, a parse status and issues,
and the parser version. The same spelling is parsed once per collection and
reused across source DATs. This is a parse cache, not a canonical title table.
`public.archive.archive_name_id` references that ID. Parser output can change
without changing the identity or its archive references.

An example from TOSEC-ISO:

```text
archive_name:    4 Wheel Thunder v1.002 (2000)(Midway)(US)[!].zip
title_candidate: 4 Wheel Thunder
extension:       .zip
tags:            v1.002, (2000), (Midway), (US), [!]
```

Each JSON tag has `value`, `delimiter`, `start` and `end`. For example:

```json
{"value": "Midway", "delimiter": "()", "start": 29, "end": 37}
```

Offsets are zero-based character offsets into the original archive name, with
an exclusive end. The delimiters are `()`, `[]`, or an empty string for a bare
token. Whitespace inside groups, duplicate tags, nested groups and original
ordering are preserved. `(En,Fr)` stays one unqualified value; it is not split
into language records. No region, publisher, language, dump-state or other
semantic classification is stored yet.

## Parsing rules and limits

- A contiguous suffix of balanced parenthesis/square-bracket groups is extracted.
  Nested groups such as `(Moz(IC)art)` remain a single tag.
- Leading square-bracket groups such as `[BIOS]` are extracted as raw tags.
- TOSEC and TOSEC-ISO use the date/publisher group layout as a boundary when
  present, retaining title parentheses before it. A preceding `(demo...)` group
  is included in the tag suffix. Conservative trailing `v...` and `Rev ...`
  forms are also extracted as bare tags. No-Intro and Redump keep unbracketed
  text in the title candidate.
- Original punctuation, capitalization, spelling and trailing articles such as
  `, The` are retained. No cross-region or cross-collection title merging occurs.
- Malformed delimiters, groups remaining inside titles, legacy `ZZZ-UNK-` names,
  missing suffixes and other uncertainty are marked `review`. Raw input is
  always retained. Unsupported suffix layouts such as `.pce.zip` need review.

`parsed` means the structural rules succeeded, not that the candidate is a
verified canonical title. A parenthetical title ending can still resemble a tag;
later source-specific rules and review can refine these boundaries. Tag meanings
and the Redump FXGA release overrides are deferred.

## Apply and refresh

The original DDL is in migration 003; 004 added stable name IDs. To move an
existing 004 database to the current `etl` schema, apply 005 once:

```sh
psql -X -v ON_ERROR_STOP=1 -f sql/migrations/005_etl_schema.sql
```

See the [SQL index](../sql/README.md#migrations) for older prerequisites.

Install `requirements.txt` and configure the ignored repository `.env` with
your external database connection. The CLI loads it automatically; exported
variables take precedence. For `psql`, first export these settings as shown in
the [root README](../README.md#database-layers).

```sh
python -m gamedb sync
```

Source synchronization first registers names and persistent archive IDs. New
names have `parse_status = 'pending'` until the parser runs. The parser reads
names referenced by current archives and updates parsed fields by ID in one
transaction. By default it processes pending or older parser versions.
`python -m gamedb parse-names --reparse` recomputes all current names without
rewriting unchanged output. Bump `PARSER_VERSION` whenever parsing rules change.
The parsing code lives in `gamedb/romvault/`. Parser results are derived data;
do not put manual canonical-title decisions in these fields.

Historical names remain in the cache if a later export no longer contains them.
Use `etl.v_archive` for current archives after source synchronization.

## Querying

```sql
-- Source archives with DAT, system, title candidate and raw tags.
-- One row per archive_id, with system_id, dat_id and archive_name_id.
SELECT * FROM etl.v_archive;

-- Unique names requiring review, independent of how many DATs use them.
SELECT * FROM etl.v_archive_name_review ORDER BY romset, archive_name;

-- One row per tag, including its position and original delimiters.
SELECT * FROM etl.v_archive_tag;

-- Vocabulary inventory for the later nomenclature work.
SELECT romset, delimiter, tag_value, count(*) AS occurrences
FROM etl.v_archive_tag
GROUP BY romset, delimiter, tag_value
ORDER BY romset, occurrences DESC;
```

`etl.v_archive` retains separate rows for identical archive names in different
DATs or systems. Its `staged_row_count` is the number of associated staging rows,
not a count of unique files across export runs. New unprocessed names appear
with `parse_status = 'pending'`.

At the raw staging boundary, all three source identifiers are still needed to
attach an archive ID to exported files:

```sql
WITH archives AS MATERIALIZED (SELECT * FROM etl.v_archive)
SELECT rf.*, a.archive_id, a.system_id,
       a.title_candidate, a.tags, a.parse_status
FROM staging.rv_files rf
LEFT JOIN archives a
    ON a.dat_path = rf.dat_root_full_name
   AND a.dat_name = rf.dat_name
   AND a.archive_name = rf.game_display_name;
```

`etl.v_archive` itself now joins persistent tables by ID without scanning
staging. Source synchronization performs the staging scan. Future core file
records can reference archive/release IDs directly; only raw import matching
needs source strings.

Run the parser tests with:

```sh
python -m unittest discover -s tests -v
```
