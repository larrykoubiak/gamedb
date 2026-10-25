# GameDB

GameDB turns a retained RomVault export into a browsable, preference-ranked game
catalog. The code is split into three applications with distinct ownership:

| Package | Owns | Command |
| --- | --- | --- |
| `gamedb.derive` | `ref` and `derived`: source interpretation and stable inventory | `python -m gamedb derive` |
| `gamedb.catalog` | `catalog`: consumer projection, identity, scores and media | `python -m gamedb rebuild` |
| `gamedb.explorer` | Read-only HTTP pages and queries | `python -m gamedb serve` |

The data flow is deliberately one-way:

```text
RomVault + reviewed integrated packages + recovered history + reference
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
       software identity, cached ranking and selected media
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

# A user preference changed; refresh scoring and preference-aware media
python -m gamedb rebuild --from-layer scoring
```

After a full derivation, build the complete consumer projection with
`python -m gamedb rebuild`. Use `--plan`, `--layers`, `--from-layer`, or
`--through-layer` to inspect or select its SQL layers.

## Integrated releases

Reviewed ZIP packages that are intentionally outside RomVault can be imported
without adding rows to `staging.rv_files`. The maintained manifest supplies the
catalog title and system while every ZIP member is CRC-checked and SHA-1 hashed:

```sh
python -m gamedb import-integrated /mnt/synology/backup/games/Undub
python -m gamedb derive --rebuild
python -m gamedb rebuild
```

The Undub collection is described by
[`reference/integrated_releases.csv`](reference/integrated_releases.csv). All
of its releases use the `undub` modification tag, including packs whose source
filename describes a narrower audio, video, or edit fix.

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
docker compose run --build --rm catalog-builder rebuild --from-layer scoring
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
The Libretro checkout is expected at `./data/libretro-thumbnails`; the catalog
builder caches its Git path index in `./data/media/cache` and the explorer
serves only selected image files from that read-only checkout.

The deployment stack also exposes the independent tool targets:

```sh
docker compose --profile tools run --build --rm deriver \
  python -m gamedb.derive --plan
docker compose --profile tools run --build --rm catalog-builder \
  python -m gamedb.catalog rebuild --from-layer scoring
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
title has exactly one source-backed anchor. This is a conservative typed rule
rather than a fuzzy title match. Remaining releases are grouped by exact title.
Importing history alone never changes the consumer catalog. Rebuild with
`python -m gamedb rebuild --from-layer software`.

## LaunchBox metadata

Download and retain a source snapshot, then import it into staging:

```sh
mkdir -p data/launchbox
curl -fL --retry 2 https://gamesdb.launchbox-app.com/Metadata.zip \
  -o data/launchbox/Metadata.zip
python -m gamedb import-launchbox import data/launchbox/Metadata.zip
python -m gamedb import-launchbox report --output data/launchbox/report-001
```

The ZIP SHA-256 identifies the snapshot; importing identical bytes again is a
no-op. Game, alternate-name and platform records retain their source fields and
XML in `staging.launchbox_record`. Image references can be imported separately
with the commands below; emulator rows remain only in the retained ZIP.

The report uses explicit `reference/launchbox_platforms.csv` mappings and exact
normalized names, including source aliases and catalog member titles. It keeps
numbers, accents and edition qualifiers; there is no fuzzy matching. A candidate
is `unique` only when both the catalog software and LaunchBox game have a single
counterpart within that canonical system. Ambiguous candidates get a second pass
using existing release dates and publisher/developer facts. A literal primary
title needs a matching year or company; an alias needs both. Known conflicting
companies/years and tied evidence leave the candidate unresolved. Multiple
catalog entries may receive `resolved_shared` enrichment links to the same game
without merging their identities; other resolutions use `resolved_source`.
These are evidence-backed candidates, not manually verified identity links.

Each new output directory contains `summary.json` (coverage and missing-field
counts), `matches.csv` (all software, statuses, titles, candidate/selected IDs, corroborating facts and resolution rules), and
`matched_games.jsonl` (source fields and aliases for selected candidates). Reports
record the source and mapping checksums. Use `--revision ZIP_SHA256` to select an
older import and `--platform-map PATH` to test another map. Numeric software IDs
are build-local, so regenerate the report after rebuilding the catalog.

Import and report commands leave the catalog unchanged. To publish selected
matches alongside the RDB metadata:

```sh
python -m gamedb rebuild --layers metadata
```

The metadata layer recalculates matches against the current catalog and publishes
both providers atomically. It retains competing values, ranks SHA-1-backed RDB
claims first, and gives LaunchBox claims zero matched content hashes. Evidence
includes the LaunchBox game ID, source row, matcher version, mapping checksum,
match method and corroborating facts. LaunchBox claims are never used to
corroborate their own future matches. Unresolved candidates stay excluded, and
software identities are not merged. Missing optional sources are supported.

The importer and reporter are included in the deriver image; mount the ZIP/report
directory when running them in a container. The metadata builder is included in
the catalog-builder and explorer images.

### LaunchBox artwork fallback

After metadata has been published, import the image references from the same ZIP
and fill missing artwork slots:

```sh
python -m gamedb import-launchbox images data/launchbox/Metadata.zip
python -m gamedb import-launchbox media
```

The image import is atomic and idempotent. `staging.launchbox_image` retains all
image references; only Box - Front, Screenshot - Gameplay, Screenshot - Game
Title and Clear Logo are selected. Selection follows published LaunchBox game
links, prefers artwork compatible with the preferred release's region, and
fills only missing `boxart`, `snap`, `title` and `logo` slots. Existing Libretro
choices are preserved. The regular media rebuild runs this fallback after
Libretro selection, so the additions survive catalog rebuilds.

Images are fetched on demand from `https://images.launchbox-app.com/`, verified
against the source CRC32 when available, and cached under
`GAMEDB_LAUNCHBOX_IMAGE_CACHE` (default `/data/media/launchbox`). Both Compose
explorers mount a persistent writable `data/media/launchbox` directory. A failed
download leaves no cache entry and can be retried. Only selected image filenames
can be fetched through the server; there is no arbitrary remote-URL proxy.

Launcher snapshots retain the existing media shape: `media.<kind>.path` is used
under `/media/`, including `launchbox/<kind>/<filename>` paths. A `provider` field
identifies the source. Artwork changes contribute to the catalog revision/ETag;
clients should revalidate cached snapshots. The explorer image must be rebuilt
when introducing the LaunchBox route; no launcher-specific image downloader is
needed.

## Libretro database staging

Keep a pinned upstream checkout beside the thumbnail checkout:

```sh
git clone --depth 1 https://github.com/libretro/libretro-database.git \
  data/libretro-database
python -m gamedb import-rdb data/libretro-database
```

The import records the Git revision, compiled RDB checksums and every raw typed
entry in `staging.libretro_rdb_*`. Common identity fields are additionally
normalized for matching, but no metadata is promoted to releases or software
at import time. Running the same revision again is a no-op; use `--replace`
only to repair that exact snapshot.

After import, build the relational software projection with:

```sh
python -m gamedb rebuild --layers metadata
```

Only exact SHA-1s resolving to one current software identity are accepted.
`catalog.software_fact` retains every competing value with support counts and a
rank; `catalog.software_fact_evidence` traces it back to the RDB row and matched
content. Region, serial, date and ratings remain release-level staging claims
rather than being flattened onto software.

The explorer treats recovered and generated groupings as accepted catalog
facts and exposes **Correct…** when an exception is found. Working decisions
are stored durably in `app.software_correction`, keyed by canonical
system and the complete release-content signature, then applied by rebuilding
the software and scoring layers. An assignment follows a signed target release
to its current software; a separation creates a manual software identity.
Mutation is gated by `GAMEDB_ENABLE_CORRECTIONS`; the workstation
`compose.dev.yaml` enables it, while the public deployment remains read-only by
default.

### Consumer catalog snapshots

Appliance clients can cache the preferred-release projection without replaying
the explorer's paginated queries:

```text
GET /api/v1/catalog
GET /api/v1/systems/{systemKey}/software
```

Versioned API requests require `Authorization: Bearer <GAMEDB_API_KEY>`. Keep
the key in the deployment environment rather than source or launcher config.

The catalog manifest provides the current scoring generation and stable system
keys. A system snapshot returns every preferred software row for that system,
including the preferred release content signature, selected artwork, and a
`softwareFacts` array of ranked metadata candidates with source support. Both
routes provide an ETag and honor `If-None-Match` with `304 Not Modified`.
For launcher metadata, read `items[].softwareFacts` on the system snapshot.
LaunchBox contributes `description`, `developer`, `publisher`, `genre` and
`player_count` through the same structure as RDB facts:

```json
{"key": "genre", "values": [{"value": "Platform", "rank": 1,
  "sourceProvider": "launchbox", "matchedContentCount": 0}]}
```

This abbreviated example omits provenance fields. `values` are ordered by rank
(best first); RDB exact-content claims rank ahead of LaunchBox title matches.
A simple launcher can display `values[0].value` for each key. Values are strings,
including player counts, and missing fields are absent (or `softwareFacts` is
empty). Identical values may appear from both providers; `candidateCount` counts
source claims, not distinct texts. Keep provenance if presenting alternatives.
`matches` includes the match method, LaunchBox `databaseId` and corroboration
`basis` when available. `sourceRevision` identifies the source snapshot.

The metadata source revision/count and artwork content signature contribute to
`catalogRevision`, so metadata imports and artwork changes invalidate snapshot ETags. Revalidate with
`If-None-Match` as usual; no per-game metadata requests are needed.

Numeric database IDs remain present for compatibility but are rebuild-local;
clients should persist the system key and release content signature instead.

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

## Arcade import and installation

MAME uses versioned machine definitions alongside RomVault storage inventory.
Import matching full `-listxml` output and an arcade-only classification DAT:

```sh
python -m gamedb import-arcade data/arcade/mame-0.285/XML/mame_724_0.285.xml \
  --arcade-dat 'data/arcade/mame-0.285/DATs/MAME 0.285 (arcade).dat' \
  --rom-dat-path 'DatRoot/Arcade/MAME/ROMs/MAME 0.285 ROMs (split).xml' \
  --chd-dat-path 'DatRoot/Arcade/MAME/CHDs/MAME 0.285 CHDs (merged).xml'
python -m gamedb derive --from-layer reference
python -m gamedb rebuild
```

The importer retains metadata and input SHA-256s in `staging.arcade_*`; replaying
identical inputs is a no-op. One active version per emulator is currently supported;
conflicting snapshots are rejected rather than mixing dependencies. Subsequent interpretation changes need only
`derive --layers arcade` and a catalog rebuild. Inputs under `data/arcade/` are
ignored by Git. Runtime containers need the retained database metadata, not the
original XML files. The deriver and explorer include the arcade module.

Arcade appears under `Various / Arcade`. MAME's explicit parent/clone families
form software identities; BIOS/device definitions remain support inventory.
Console/computer machines are excluded using the classification DAT. FBNeo uses
its arcade-only DAT and the same canonical Arcade system. FinalBurn Alpha is not imported.
Shared chips and split ZIP contents are excluded from automatic game identity
and Libretro metadata matching.

The authenticated `GET /api/v1/releases/{signature}/install-manifest` endpoint
returns schema version 2 for arcade. Its signature identifies the versioned
machine definition (`signatureKind=machine_definition`), not a complete ZIP
content signature. The software snapshot's `preferredReleaseSignature` and the
release listing's `installSignature` provide this value. Ordinary release
manifests remain schema version 1.

A complete arcade manifest includes a `bundleUrl`:
`GET /api/v1/releases/{signature}/install-bundle`. Extract the ZIP64 bundle into
an installation directory and launch `launchPath` with `preferredCore`.
`compatibleEmulators` records core filenames, DAT versions, input SHA-256s, and
`dat_validated` evidence. This validates requirements, not actual emulation.
The bundle contains `gamedb-install.json`, `roms/<machine>.zip`, any required
parent/BIOS/device ZIPs, and only the selected disks at
`roms/<machine>/<disk>.chd`. CHDs stay outside the ROM ZIPs. Fully inherited and
disk-only variants receive an empty launch ZIP while their content remains in
the dependency ZIPs. Bundles stream without recompressing CHDs or making a
multi-GB temporary copy; generated bundle downloads do not support resumption.

Completeness is separate from MAME's reported emulation status. Missing ROMs,
undumped requirements, samples, missing host files or changed ZIP member
size/CRC produce an incomplete manifest and block bundle downloads with HTTP
409. This first MAME implementation has no samples inventory importer, so
sample-dependent machines explicitly remain incomplete. Disk requirements use
RomVault's `alt_sha1_hex` content hash; `sha1_hex` remains the physical file hash.
Manifest checks validate file presence, CHD size and ZIP member size/CRC against
the inventory; they do not rehash large CHDs on every request or prove emulator
execution. Keep the target core compatible with the manifest's emulator definitions.

Import FBNeo after its ROM inventory has been exported to `rv_files`:

```sh
python -m gamedb import-arcade '/path/to/FinalBurn Neo v1.0.0.02 (ClrMame Pro XML).dat' \
  --emulator FBNeo \
  --rom-dat-path 'DatRoot/Arcade/FinalBurn Neo/roms/arcade/FinalBurn Neo v1.0.0.02 (ClrMame Pro XML).dat'
python -m gamedb derive --from-layer reference
python -m gamedb rebuild
```

FBNeo DAT CRC/size declarations resolve against version-scoped inventory. Cross-emulator
family links require equality of the complete game-ROM SHA-1/size sets, excluding
BIOS contents, and an unambiguous MAME family. Partial shared content never links
families. A single unchanged bundle is marked compatible with both only if it
satisfies both dependency graphs, hashes and member names with the same launch name.
Arcade ranks complete packages first, then non-preliminary emulation, then user
preference scores. The default FBNeo preference is +200; readiness does not distort
the visible score with huge negative penalties. MAME remains the fallback.

Both MAME and FBNeo thumbnail directories are searched. Neo Geo is retained as
`hardware=SNK Neo Geo`, independently of the canonical Arcade system and selected
core. AES/MVS mode selection is not inferred from shared ROM hashes; the launcher
currently retains the user's core BIOS settings. FBNeo Killer Instinct HDD sets
remain incomplete until their external HDD requirements are imported explicitly.

FBNeo sample DATs can be imported with `--samples-dat` and
`--samples-dat-path` alongside the ROM import. Samples resolve through `rv_files`
using the sample DAT CRC/size and retained inventory SHA-1. Bundles include
`system/fbneo/samples/<set>.zip`; `systemDirectory` tells the launcher to use that
private directory through a per-game RetroArch append config. To update an
existing catalog without rebuilding identities, add `--refresh-samples`, then
run `python -m gamedb.catalog rebuild --layers scoring`. MAME samples still
require a separate importer; FinalBurn Alpha inventory is not treated as FBNeo.
