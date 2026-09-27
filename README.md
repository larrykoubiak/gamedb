# GameDB

RomVault-based software catalogue, building toward **System → Title → Release → File**.
Systems and source archives currently have stable IDs; canonical titles and releases
will be reconciled in later passes.

## Start here

| Location | Purpose |
| --- | --- |
| [`data/reference/`](data/README.md#reference-data) | Manually maintained canonical system list |
| [`data/research/`](data/README.md#research-material) | Exported DAT inventory and TOSEC workbook used for analysis |
| [`sql/migrations/`](sql/README.md#migrations) | Numbered database changes, in one sequence |
| [`sql/queries/`](sql/README.md#queries) | Read-only exploration queries |
| [`gamedb/`](gamedb/) | Current CLI, source synchronization and filename parser |
| [`docs/database.md`](docs/database.md) | Current tables, relationships and schema boundaries |
| [`tests/`](tests/) | Python checks and SQL verification under `tests/sql/` |
| [`archive/schema/`](archive/schema/README.md) | Superseded schema drafts and notes |
| [`app/`](app/README.md) | Legacy Libretro/thumbnail/Django application retained for reuse |

## Database layers

| Schema | Responsibility |
| --- | --- |
| `staging` | Raw imported RomVault data (`rv_files`) |
| `ref` | Reserved for reference data maintained by hand and loaded from static files |
| `etl` | Source DATs, source-name parses, discovered mappings, views and refresh functions |
| `public` | Persistent catalogue entities: `system` and `archive` today |

Migration **005** moves the generated objects out of `ref` into `etl`, preserving
IDs and reviewed decisions. `ref` is currently empty. The existing canonical CSV
was the initial system seed; it is not automatically loaded on every sync.

For a database upgraded through 004, export the settings from your local `.env`
before using `psql` (which does not load that file itself):

```sh
set -a
. ./.env
set +a
psql -X -v ON_ERROR_STOP=1 -f sql/migrations/005_etl_schema.sql
```

See the [SQL index](sql/README.md) before applying earlier scripts. A fresh database
still needs the staging export and original prerequisites; the numbered files
are not a complete bootstrap from an empty database.

## Normal workflow

Install `requirements.txt`. For a new checkout, copy `.env.example` to `.env`
and fill in `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and `PGPASSWORD` for your
external Postgres server. Keep an existing `.env` when updating a checkout.

The CLI loads the repository's `.env` automatically. Exported variables take
precedence; values in the file are read literally, without `${...}` expansion.
`.env` is ignored by Git and is never copied into the image. For `.pgpass`
authentication, omit `PGPASSWORD` from `.env`.

```sh
python -m gamedb sync
```

`sync` discovers system mappings, refreshes DAT/archive identities, and parses
new ZIP names. The individual steps are:

```sh
python -m gamedb sync-sources
python -m gamedb parse-names
python -m gamedb parse-names --reparse
```

See [system mapping](docs/system_mapping.md) for reviewed aliases and
[archive names](docs/archive_names.md) for title candidates and unqualified tags.

## Docker

Compose runs the current CLI against the external database configured in `.env`.
It does not create a Postgres server or manage database storage. Use a `PGHOST`
reachable from the container; `localhost` inside a container refers to that
container. The old Django and Cloudflare services are opt-in under the `legacy`
profile and use the obsolete Libretro model. No current web UI has been built yet.

```sh
docker compose run --build --rm app python -m gamedb --help
docker compose run --rm app python -m gamedb sync
```

## Verification

```sh
python -m unittest discover -s tests -v
```

To include the database integration check, configure `.env` as above:

```sh
GAMEDB_INTEGRATION=1 python -m unittest discover -s tests -v
```

It loads `.env`, copies schema only into a disposable database, verifies identity preservation,
schema placement and constraints, then drops the database. The connection needs
permission to create databases. The configured source database is read only.
The [SQL index](sql/README.md#verification) also describes mapping verification.

## Secrets (SOPS)

Encrypt `.env` into `.sops.env`:

```sh
sops --encrypt --output .sops.env .env
```

Decrypt for local use:

```sh
sops --decrypt --output .env .sops.env
```
