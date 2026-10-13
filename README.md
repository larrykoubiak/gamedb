# GameDB

RomVault-based software catalogue with a **System → Title → Release → Package → File**
consumer hierarchy.
The database is replayable from the retained raw RomVault import and maintained
reference files.

Start with [the current project status and handoff](docs/status.md) for the
verified snapshot, terminology, known limitations and next architectural step.

## Layers

| Schema | Responsibility |
| --- | --- |
| `staging` | Raw RomVault input; currently only `rv_files` |
| `ref` | Maintained inputs loaded from `data/reference/` |
| `derived` | Fully rebuildable parsing and classification results |
| `catalog` | Reconciled systems, titles, releases and files |
| `app` | Durable local users and personal scoring preferences |

The implemented rebuild loads canonical systems and the complete reviewed
source mapping, then recreates the derived/catalog data and disposable score
cache without modifying staging or durable preferences:

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

See [the database model](docs/database.md), [system mapping](docs/system_mapping.md),
the [archive-name rules](docs/archive_names.md), and the
[SQL rebuild index](sql/README.md).

## Archive-name parser

The pure Python parser and classifier are independent of database persistence.
Inspect one filename with:

```sh
python -m gamedb parse-name No-Intro 'Example (USA) (En,Fr).zip' --classify
```

Their rules and limits are documented in [archive names](docs/archive_names.md).
The archive-name rebuild persists archive associations, parsed records, raw
tags and their classifications relationally under `derived`.

The final SQL step projects those results into consumer-facing systems,
exact-title browse/search clusters, releases, normalized facts with source
evidence, packages and files. Explicitly numbered media parts are grouped
conservatively when their title and all non-media tags agree.

## Verification

```sh
python -m unittest discover -s tests -v
```

The parser uses only the Python standard library. A minimal optional container is
available for running the same CLI.

```sh
docker compose run --build --rm app python -m gamedb --help
```

## Secrets

Connection settings live in the ignored `.env`; export them before invoking
`psql`. To preserve them with SOPS:

```sh
sops --encrypt --output .sops.env .env
sops --decrypt --output .env .sops.env
```
