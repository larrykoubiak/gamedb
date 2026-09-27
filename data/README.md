# Data files

These folders distinguish maintained inputs from material used for exploration.
Database storage, ROMs and media under `data/` remain ignored by Git.

## Reference data

[`reference/canonical_systems.csv`](reference/canonical_systems.csv) is the original
manually maintained list, moved from `canonical.csv` without changing its contents.
Its columns are `canonical_manufacturer_name` and `canonical_system_name`.

It supplied the initial canonical systems, which now live in `public.system` with
stable IDs. Editing the CSV currently does **not** update the database: no ongoing
reference-file loader has been implemented. System renames in the live catalogue
must preserve `public.system.id`; recreating systems from CSV would break that
identity contract. A future loader needs an explicit policy for additions and renames.

`ref` is reserved for manually maintained database reference tables. None have
been introduced yet after moving generated records to `etl`. Reviewed alias
decisions still live in `etl.system_mapping`; their original seeds and the NEC
policy are recorded in migrations 001 and 002. Moving those decisions into a
maintained reference file/table is a separate step from this schema cleanup.

## Research material

| File | Origin and purpose |
| --- | --- |
| [`research/romvault_dat_paths.csv`](research/romvault_dat_paths.csv) | Former `romset.csv`; exported DAT paths split into components, used to explore collection layouts |
| [`research/tosec.xlsx`](research/tosec.xlsx) | Existing TOSEC workbook, retained as research material |

These files are not read by `python -m gamedb sync` and are not maintained
reference tables. Their contents were preserved during the move. Regenerating
an export should not overwrite the curated canonical list.

Exploration SQL lives in [`sql/queries/`](../sql/README.md#queries). Database
migrations live in [`sql/migrations/`](../sql/README.md#migrations).
