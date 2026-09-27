# RomVault transforms

`staging.rv_files` is the raw source. `etl` contains source identities, mappings
and parsing results. `ref` is reserved for maintained reference data.
Canonical systems and persistent archives live in
`public`; see the [core model](database.md).

## Systems

`etl.system_mapping` retains each parsed source manufacturer/system pair and
links it to `public.system.id` through `system_id`. Its `match_method` and `notes`
record how the match was made. The former `ref.canonical_system` table was moved
to `public.system` by migration 004. Migration 005 moved the generated mapping
table and transforms into `etl`, preserving all reviewed decisions.

Matching follows this order:

1. Preserve existing explicit aliases and reviewed decisions.
2. Match the exact canonical manufacturer and system name.
3. Accept a unique match after ignoring case, whitespace and common separators.
4. Retain ambiguous or unmatched pairs with a null `system_id`.

Significant symbols such as `+`, `#` and `@` remain significant. The source view
currently covers No-Intro, Redump, TOSEC and TOSEC-ISO.

```sql
SELECT m.*, s.manufacturer_name, s.name AS canonical_system_name
FROM etl.system_mapping m
LEFT JOIN public.system s ON s.id = m.system_id;

SELECT * FROM etl.v_romset_system;
SELECT * FROM etl.v_system_mapping_review;
```

`etl.v_romset_system` exposes `system_id` plus display names. Raw source strings
are used at the ingestion boundary; core relationships use IDs. An update to a
canonical display name does not change the ID or invalidate existing mappings.

After a source import or mapping change:

```sh
python -m gamedb sync
```

This refreshes system aliases, DAT/archive identities and name parses. The
individual refresh functions are:

```sql
SELECT etl.refresh_system_mapping();
SELECT * FROM etl.refresh_archives();
```

To record a reviewed alias in `etl.system_mapping`, update `system_id`, set `match_method = 'manual'`,
and add a note. Then refresh archives so assignments inherited from DATs follow
the new target. Manual per-archive system assignments remain intact.

The reviewed NEC mappings remain:

| Source label | Canonical system |
| --- | --- |
| PC-88 series | PC-8801 |
| PC-98 series | PC-9801 |
| PC-FX & PC-FXGA | PC-FX |
| PC-FXGA | PC-FXGA |

PC-88VA, PC-9821 and PC-FXGA keep their own canonical IDs. Overrides based on
FXGA tags in individual Redump release names are deferred.

## Archives and tags

See [archive_names.md](archive_names.md) for the parser rules and unqualified tag
format. `public.archive` references both `etl.dat.id` and `etl.archive_name.id`.
`etl.v_archive` joins these IDs to provide convenient source and display fields.

## Migrations and verification

All migrations now live under [`sql/migrations/`](../sql/README.md#migrations).
001–003 describe the original transform setup, 004 assigns stable IDs, and 005
separates ETL state from the reference schema. Apply only pending upgrades;
earlier scripts should not be rerun on the current schema.

The system mapping checks use the current ID-based schema:

```sh
psql -X -v ON_ERROR_STOP=1 -f tests/sql/verify_system_mapping.sql
```

For `psql`, first export the connection settings from `.env` as shown in the
[root README](../README.md#database-layers). The Python CLI loads that file itself.

They cover matching, ambiguity, foreign keys, uniqueness and preservation of
manual decisions. Synthetic fixtures are rolled back. Parser and core identity
checks are documented in the root README.
