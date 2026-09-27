# SQL index

SQL files are grouped by how they are used, independently of database schema names.
Normal imports use `python -m gamedb sync`; they do not rerun migrations.

## Migrations

| File | Purpose | When to use |
| --- | --- | --- |
| [`001_system_mapping.sql`](migrations/001_system_mapping.sql) | Original alias matching and review views | Historical, before 004 |
| [`002_nec_system_mapping.sql`](migrations/002_nec_system_mapping.sql) | Reviewed NEC mappings | Historical, after 001 and before 004 |
| [`003_archive_names.sql`](migrations/003_archive_names.sql) | Original filename parsing cache | Historical, before 004 |
| [`004_system_archive.sql`](migrations/004_system_archive.sql) | Stable canonical system, DAT, name and archive IDs | Upgrade from the original 001–003 transforms |
| [`005_etl_schema.sql`](migrations/005_etl_schema.sql) | Move imported and generated objects from `ref` to `etl` | Current upgrade from 004; safely skips if already applied |

Use `psql -X -v ON_ERROR_STOP=1 -f <file>` with your libpq connection settings.
Export them from the ignored `.env` file as shown in the
[root README](../README.md#database-layers); `psql` does not load `.env` itself.
Apply only the needed upgrade. **Do not run all files against the current database.**
Earlier scripts address the table names and columns that existed at that time;
their SQL bodies remain historical records. New schema changes get a new number.

The current migration ledger is `etl.schema_migration`. It records 004 and 005;
001–003 predate the ledger. Migration 005 updates function bodies as well as object
locations and preserves table IDs, identity sequences, views and foreign keys.

These migrations start from an already populated `staging.rv_files`, the original
`ref.v_romset`, and the original canonical reference table. They are not a full
fresh-install bootstrap. The old [v2 draft](../archive/schema/v2_core_draft.sql)
and `app.cli.main init-db` belong to a different model.

## Queries

These are read-only inspection queries, not migrations or loaders:

| File | Purpose |
| --- | --- |
| [`source_system_coverage.sql`](queries/source_system_coverage.sql) | Former `canonical.sql`; lists source manufacturer/system pairs and collection coverage |
| [`parse_romsets.sql`](queries/parse_romsets.sql) | Former `romsets.sql`; explores DAT path/name parsing, corresponding to `etl.v_romset` |

## Verification

[`tests/sql/verify_system_mapping.sql`](../tests/sql/verify_system_mapping.sql)
checks mapping behavior using synthetic fixtures and rolls the transaction back:

```sh
psql -X -v ON_ERROR_STOP=1 -f tests/sql/verify_system_mapping.sql
```

Run it against a synchronized development database. Sequence values may advance
even though fixture rows are rolled back. Python parser and disposable database
checks are described in the [root README](../README.md#verification).
