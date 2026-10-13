# SQL rebuild

`staging.rv_files` is retained as the raw RomVault import. Everything else is
being replaced by replayable scripts under `rebuild/`. Historical migrations and
queries for the superseded `etl/public` layout have been removed.

Run scripts from the repository root so `psql` can resolve reference CSV paths:

```sh
set -a
. ./.env
set +a
psql -X -v ON_ERROR_STOP=1 -f sql/rebuild/000_reset.sql
psql -X -v ON_ERROR_STOP=1 -f sql/rebuild/001_reference_and_dat.sql
python scripts/rebuild_archive_names.py
psql -X -v ON_ERROR_STOP=1 -f sql/rebuild/003_catalog.sql
psql -X -v ON_ERROR_STOP=1 -f sql/rebuild/004_release_scores.sql
```

| File | Purpose |
| --- | --- |
| [`000_reset.sql`](rebuild/000_reset.sql) | Preserve `staging.rv_files` and remove all superseded GameDB schemas/tables |
| [`001_reference_and_dat.sql`](rebuild/001_reference_and_dat.sql) | Load canonical systems and complete source mappings into `ref`, then rebuild `derived.dat` |
| [`002_archive_names.sql`](rebuild/002_archive_names.sql) | Internal bulk-load step used by `scripts/rebuild_archive_names.py`; rebuild parsed archive records, tags, classifications and DAT/archive associations |
| [`003_catalog.sql`](rebuild/003_catalog.sql) | Project parsed records into title clusters, releases, normalized facts with evidence, packages and files |
| [`004_release_scores.sql`](rebuild/004_release_scores.sql) | Maintain local users/preferences and atomically compile the disposable release-score cache |

The Python wrapper selects names from staging through `derived.dat`, writes
temporary bulk-load files, invokes `002_archive_names.sql`, and removes the files.
The final SQL step preserves `app.app_user` and `app.user_preference`, seeds the
`default` user only when missing, and atomically replaces the catalog score
cache. Edit preferences and rerun only `004_release_scores.sql` to rescore.
