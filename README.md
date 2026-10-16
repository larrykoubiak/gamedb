# GameDB

GameDB turns a retained RomVault export into a browsable, preference-ranked game
catalog. The code is split into three applications with distinct ownership:

| Package | Owns | Command |
| --- | --- | --- |
| `gamedb.derive` | `ref` and `derived`: source interpretation and stable inventory | `python -m gamedb derive` |
| `gamedb.catalog` | `catalog`: consumer projection, facts, identity and score cache | `python -m gamedb rebuild` |
| `gamedb.explorer` | Read-only HTTP pages and queries | `python -m gamedb serve` |

The data flow is deliberately one-way:

```text
staging.rv_files + recovered history + reference
                  │
                  ▼
       Python derivation pass
       ref + derived
       DATs, systems, packages, paths, files,
       titles, raw tags, typed assertions, media
                  │
                  ▼
       SQL consumer projection
       catalog systems, titles, releases, facts,
       software identity and cached ranking
                  │
                  ▼
             explorer
```

The two executable manifests tell that story in detail:

- [`derive.yml`](derive.yml) declares the Python extraction layers.
- [`pipeline.yml`](pipeline.yml) declares the downstream SQL projection layers.

## Running only what changed

A full derivation is destructive and must be explicit:

```sh
python -m gamedb derive --plan
python -m gamedb derive --rebuild
```

Routine changes select their actual boundary. They do not silently replay
staging, path resolution, or name parsing:

```sh
# A path mapping changed
python -m gamedb derive --layers paths

# Parser/classifier rules changed; stable inventory is reused
python -m gamedb derive --from-layer names

# A user preference changed; derived data is untouched
python -m gamedb rebuild --layers scoring
```

After a full derivation, build the complete consumer projection with
`python -m gamedb rebuild`. Use `--plan`, `--layers`, `--from-layer`, or
`--through-layer` to inspect or select its SQL layers.

## Inspecting names

The parser can be exercised without changing the database:

```sh
python -m gamedb parse-name No-Intro 'Example (USA) (En,Fr).zip' --classify
```

See [the database model](docs/database.md), [archive-name rules](docs/archive_names.md),
[current status](docs/status.md), and [SQL index](sql/README.md).

## Explorer

There are two Compose entry points with deliberately different database
ownership:

- `compose.yaml` is the self-contained `larry-tower` deployment and owns
  PostgreSQL.
- `compose.dev.yaml` runs local code against the `PG*` connection in `.env` and
  never starts PostgreSQL.

For workstation development, add this to the local `.env` alongside the tower
connection and use ordinary Compose commands:

```env
COMPOSE_FILE=compose.dev.yaml
PGHOST=larry-tower
PGPORT=9876
GAMEDB_EXPLORER_PORT=8082
```

```sh
# Rebuild and run the local explorer against the tower database.
docker compose up --build -d

# Run one-shot tools against that same database.
docker compose run --build --rm deriver --from-layer names
docker compose run --build --rm catalog-builder rebuild --layers scoring
```

On `larry-tower`, where `COMPOSE_FILE` is not set, copy `.env.example` to `.env`,
retain the credentials that initialized the database, then start the deployment:

```sh
docker compose up --build -d explorer
```

PostgreSQL data is retained at `./data/pgdata`. Application containers connect
to `db:5432`; `PGHOST` and `PGPORT` remain useful for commands run directly on
the host. Set `GAMEDB_EXPLORER_PORT=8080` to change the explorer's host port and
`GAMEDB_POSTGRES_PORT` to change the optional host database port.

The deployment stack also exposes the independent tool targets:

```sh
docker compose --profile tools run --build --rm deriver \
  python -m gamedb.derive --plan
docker compose --profile tools run --build --rm catalog-builder \
  python -m gamedb.catalog rebuild --layers scoring
docker compose up --build explorer
```

The `tools` profile does not run derivation or catalog work automatically. It
only makes those one-shot services available when explicitly requested.

On `larry-tower`, deploy from `/srv/docker/gamedb` so the existing
`./data/pgdata` bind mount is reused. The Compose file accepts the tower's old
`POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` names as fallbacks, so
its current `.env` can be retained. To keep the existing Cloudflare tunnel and
remove the obsolete Django/ETL containers after the source tree is replaced:

```sh
docker compose --profile public up --build -d --remove-orphans
```

The explorer retains `web` as a network alias for compatibility with the
existing managed tunnel origin.

## Verification

```sh
python -m unittest discover -s tests -v
```

## Recovered identity sources

Historical GameDB databases and review artifacts can be snapshotted into
history-owned `staging.history_*` tables without affecting `staging.rv_files`:

```sh
python -m gamedb import-history \
  --python-gamedb /path/to/recovered/GameDB \
  --legacy-archive /path/to/20160605-GameDB_Backup.7z \
  --patch-workbook /path/to/patches.xlsx
```

`OLD_GAMEDB` supplies the read-only SQLAlchemy URL for the legacy relational
database. The import preserves source IDs, hashes, Parent/Clone relationships,
source trust ratings, external mappings, reviewed match scores, workbook rows,
and artifact checksums.
The `software` catalog layer interprets unambiguous historical SHA-1 matches as
recovered software identity and extends them through unambiguous Parent/Clone
groups. A unique source-backed identity cascades to the remaining releases in
its effective title; collisions stop the cascade and become review candidates.
Maybe-Intro `[n]` translations may also join an existing software identity when
their playable member filename retains one unambiguous original title and that
title has exactly one source-backed anchor. This remains typed, reviewable
`translation_member_title` evidence rather than a fuzzy title match.
Unresolved releases remain in explicit title-fallback software groups.
Importing history alone never changes the consumer catalog. Rebuild with
`python -m gamedb rebuild --from-layer software`.

The explorer's release detail table exposes **Review…** for unresolved matches
and **Correct…** for reviewed ones. Confirming the current assignment records
an `assign` decision against another signed release in the same software, or a
`separate` decision when no distinct anchor exists. Working decisions are
stored durably in `app.software_correction`, keyed by canonical
system and the complete release-content signature, then applied by rebuilding
the software and scoring layers. An assignment follows a signed target release
to its current software; a separation creates a manual software identity.
Mutation is gated by `GAMEDB_ENABLE_CORRECTIONS`; the workstation
`compose.dev.yaml` enables it, while the public deployment remains read-only by
default.

After reviewing working corrections, promote them into the version-controlled
reference CSV and its `ref` materialization:

```sh
python -m gamedb promote-corrections
```

Promoted rows remain in `app` as audit history but no longer participate as
working decisions. Reviewed reference corrections take precedence on rebuild.

Maintained corrections live in `reference/software_overrides.csv`. An `assign`
row selects one release by system, source collection, archive name, and record
index and places it in a system-scoped manual `target_key`; an `exclude` row
prevents automatic identity inheritance for that release. Every selector must
resolve to exactly one current release or the software transaction stops.

Connection settings live in the ignored `.env`; exported shell values take
precedence.
