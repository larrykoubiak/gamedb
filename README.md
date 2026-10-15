# GameDB

RomVault-based software catalogue with a **System → Title → Release → Package → File**
consumer hierarchy.
The database is replayable from the retained raw RomVault import and maintained
reference files.

Start with [the current project status and handoff](docs/status.md) for the
verified snapshot, terminology, known limitations and next architectural step.

## Applications

The repository contains two deliberately separate applications:

| Package | Responsibility | Standalone command |
| --- | --- | --- |
| `gamedb.load` | Parse staged input and rebuild disposable database layers | `python -m gamedb.load rebuild` |
| `gamedb.explorer` | Serve read-only catalog queries and browser assets | `python -m gamedb.explorer` |

`python -m gamedb` remains a convenience dispatcher for local use. The loader
depends on PyYAML and needs rebuild SQL/reference files; the explorer uses only
the standard library, `psql`, and its read-only query files.

## Layers

| Schema | Responsibility |
| --- | --- |
| `staging` | Raw RomVault input; currently only `rv_files` |
| `ref` | Maintained inputs loaded from `data/reference/` |
| `derived` | Fully rebuildable parsing and classification results |
| `catalog` | Reconciled systems, titles, releases and files |
| `app` | Durable local users and personal scoring preferences |

The executable [`pipeline.yml`](pipeline.yml) is the table of contents for the
rebuild. It loads canonical systems and the reviewed source mapping, then
recreates derived/catalog data and the disposable score cache without modifying
staging or local preferences:

```sh
python -m gamedb rebuild --plan
python -m gamedb rebuild
```

Layers can be selected without replaying unchanged upstream work:

```sh
python -m gamedb rebuild --layers scoring
python -m gamedb rebuild --from-layer catalog
python -m gamedb rebuild --through-layer archive_names
```

The runner executes the YAML in order through explicit step classes. SQL lives
under `sql/layers/<layer>/`; the archive-name step owns its Python parse/classify
pass and relational loader.

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

## Local explorer

After building the catalog and score cache, start the read-only visualization:

```sh
python -m gamedb serve
```

Open `http://127.0.0.1:8000`. The page groups systems under manufacturers and
lists the cached preferred release for every title, including scores, matching
preference reasons, normalized facts and unresolved tie counts. Expand a row to
compare every losing release, its source package and complete file hashes. It
uses the existing `psql` client and does not add an application dependency. The
read-only SQL is independently reviewable under `sql/queries/explorer/`; a
`CatalogRepository` binds and executes it while the HTTP module handles routing
and responses. The command loads missing PostgreSQL connection settings from the project `.env`;
settings already exported in the shell take precedence. Set
`GAMEDB_EXPLORER_PORT=8080` there to change the default port, or use `--port` for
a one-off override.

The parser itself uses only the Python standard library. Install the loader's
workflow dependency with `python -m pip install -r requirements-load.txt`.

The Dockerfile exposes separate images. Start the read-only explorer with:

```sh
docker compose up --build explorer
```

Run the loader as an explicitly selected tool container:

```sh
docker compose --profile tools run --build --rm loader \
    python -m gamedb.load rebuild --plan
```

## Secrets

Connection settings live in the ignored `.env`; export them before invoking
`psql`. To preserve them with SOPS:

```sh
sops --encrypt --output .sops.env .env
sops --decrypt --output .env .sops.env
```
