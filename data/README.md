# Data files

These folders distinguish maintained inputs from material used for exploration.
Database storage, ROMs and media under `data/` remain ignored by Git.

Maintained derivation inputs live in the top-level [`reference`](../reference)
directory so container builds can exclude this entire runtime-data tree. This is
important when `data/pgdata` belongs exclusively to PostgreSQL.

## Research material

| File | Origin and purpose |
| --- | --- |
| [`research/romvault_dat_paths.csv`](research/romvault_dat_paths.csv) | Former `romset.csv`; exported DAT paths split into components, used to explore collection layouts |
| [`research/tosec.xlsx`](research/tosec.xlsx) | Existing TOSEC workbook, retained as research material |

These research files are not rebuild inputs. Their contents were preserved during
the move; regenerating an export should not overwrite maintained reference files.

Replayable derivation and projection are declared by [`derive.yml`](../derive.yml)
and [`pipeline.yml`](../pipeline.yml).
