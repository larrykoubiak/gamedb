# Database model and ownership

GameDB has retained inputs, one interpreted source model, and one disposable
consumer model. The boundaries are ownership boundaries, not just naming
conventions.

| Schema | Owner | Responsibility |
| --- | --- | --- |
| `staging` | external intake | Untouched RomVault rows, reviewed integrated ZIP inventories, immutable historical snapshots, and revisioned Libretro RDB entries |
| `ref` | deriver | Version-controlled mappings and vocabularies |
| `derived` | deriver | Stable inventory plus source-faithful semantic interpretation |
| `catalog` | catalog builder | Accepted browse facts: software, releases, packages and files |
| `app` | application | Durable users/preferences plus disposable user score projections |

```text
                         DERIVATION PACKAGE
staging.rv_files ───────────┬──► DAT identity ─► system resolution
staging.integrated_* ───────┼──► package/file inventory ─► resolved package paths
reference files ────────────┴──► name parser/classifier
                              │
                              ├── source title records
                              ├── lossless raw tags + classifications
                              ├── typed assertions
                              └── typed media parts ─► source releases

                         CATALOG BUILDER
derived source releases ─► catalog titles/releases
derived assertions      ─► normalized facts + evidence
derived file hashes     ─► exact-content identity/aliases
history + file hashes   ─► software + release membership/evidence
RDB + exact SHA-1       ─► ranked software facts + row-level evidence
app preferences         ─► software-scoped scores/preferred releases
```

The deriver emits ordinary relational values. Downstream SQL never reparses a
filename, expands classifier JSON, rediscovers a path, or reloads file
inventory.

## Derivation layers

[`derive.yml`](../derive.yml) is the executable dependency story:

| Layer | Reads | Writes | Rerun when |
| --- | --- | --- | --- |
| `schema` | — | empty `ref` and `derived` contract | Explicit full development rebuild only |
| `reference` | reference files | `ref.*` | Maintained mapping/vocabulary changed |
| `dat` | staging | `derived.dat_source` | Staging DAT population or DAT parsing changed |
| `system` | DAT source + system map | `derived.dat` | System mapping changed |
| `inventory` | staging + DATs | archive names, packages, files | Staging inventory changed |
| `paths` | packages + path map | package paths | Only path mapping changed |
| `names` | stable archive names | records, tags, classifications, assertions, media | Name rules changed |
| `releases` | packages + typed records/media | source releases and membership | Name/media grouping changed |

The full path is `python -m gamedb derive --rebuild`. It is intentionally not
the default. A parser change is `--from-layer names`; a path change is
`--layers paths`. Selection is explicit rather than based on hidden scratch
state.

### Stable source inventory

| Table | Purpose |
| --- | --- |
| `derived.dat_source` | Python-parsed source DAT identity |
| `derived.dat` | DAT resolved to a reviewed canonical system |
| `derived.archive_name` | Unique source archive spelling per collection |
| `derived.package` | One DAT/archive association |
| `derived.package_path` | Independently resolved host path |
| `derived.file` | Archive members, sizes, hashes and verification state |

Packages and files do not depend on successful name parsing. Source names that
policy deliberately ignores therefore remain auditable inventory but do not
become releases.

### Semantic interpretation

| Table | Purpose |
| --- | --- |
| `derived.archive_parse` | Parse/classifier version, status and name-level issues |
| `derived.record` | Ordered source title records and their non-media grouping signature |
| `derived.tag` | Exact raw tag, delimiter and source offsets |
| `derived.tag_classification` | Separate category, rule, identifier/value and details |
| `derived.assertion` | Normalized key/value facts emitted directly by Python |
| `derived.media_part` | Typed disc/tape/side/part data |
| `derived.translation_member_title` | Original-title candidate parsed from each playable Maybe-Intro member name |
| `derived.source_release` | Source-faithful release assembled from typed records |
| `derived.source_release_package` | Package membership and media ordering |

Raw lexical evidence and semantic interpretation are separate on purpose. A
classification rule can evolve without pretending the source spelling changed.
Each assertion links to its exact raw tag.

## Consumer projection

[`pipeline.yml`](../pipeline.yml) starts at the stable derived contract:

| Layer | Main output |
| --- | --- |
| `catalog` | systems, titles, releases, packages and member files |
| `facts` | accepted normalized `release_fact` rows |
| `identity` | exact package/release signatures and accepted title aliases |
| `software` | platform software and total accepted release membership |
| `metadata` | ranked software facts and their exact RDB record/hash evidence |
| `scoring` | `app`-owned per-user score cache and preferred-release view |
| `media` | selected Libretro assets and explainable software associations |

The catalog projects every release-visible package and member file, including
its logical and resolved path, size, hashes and verification state. Consumers
therefore never need to join into `derived`. Exact SHA-1 matching takes
precedence over spelling when reconciling title clusters; accepted aliases
remain in the catalog while detailed matching work exists only in temporary
build relations.

`app.app_user` and `app.user_preference` survive catalog rebuilds. Changing a
preference requires only:

```sh
python -m gamedb rebuild --from-layer scoring
```

A preference with null `system_manufacturer` and `system_name` is global;
setting both gives it an exact canonical-system scope. Global and scoped rules
are additive, so a system rule can reinforce or offset the general policy.
Translation scoring also derives a per-user contextual role: preferred-language
fallback, redundant with an original matching a preferred locale, or
non-preferred language.

Compiled databases from a pinned `libretro-database` checkout are first
imported without changing the consumer catalog:

```sh
python -m gamedb import-rdb data/libretro-database
```

`staging.libretro_rdb_import` records the Git revision,
`staging.libretro_rdb_file` records each compiled database, and
`staging.libretro_rdb_entry` retains every typed raw record plus normalized
SHA-1, MD5, CRC, size and serial columns. Reimporting an existing revision is a
no-op unless `--replace` is supplied.

The `metadata` layer then accepts only exact SHA-1s that resolve to one current
software identity. It publishes software-oriented claims in
`catalog.software_fact` and retains every supporting RDB row and matched hash in
`catalog.software_fact_evidence`. Conflicting values are not collapsed: support
counts and `value_rank` make the leading candidate explicit while preserving
the alternatives. Release-bound RDB fields such as region, serial, date and
ratings are deliberately excluded from this software-level table.

LaunchBox source snapshots remain staging-owned. The ZIP checksum,
source URL/path, import time and record counts live in `staging.launchbox_import`.
`staging.launchbox_record` stores Game, GameAlternateName, Platform and
PlatformAlternateName source records, including their top-level XML row numbers,
raw fields and XML. Imports are atomic and identical ZIPs are idempotent.

`python -m gamedb import-launchbox report --output data/launchbox/report-001`
reads a consistent catalog/source snapshot in a read-only transaction, then
writes coverage and candidate evidence to local files. Reporting does not
promote facts or alter identity assignments.

The metadata workflow now executes a single Python-owned transaction for RDB
and LaunchBox projection. Selected LaunchBox links publish software facts with
`source_provider='launchbox'`, a 64-character ZIP SHA-256 source revision and
`matched_content_count=0`. Exact-content RDB claims retain their original
40-character revision and nonzero hash counts, and rank ahead of title matches.

In `catalog.software_fact_evidence`, `source_file_id` is provider-scoped: an RDB
file ID for Libretro, or a LaunchBox import ID. LaunchBox evidence names
`Metadata.xml` and its source row, leaves `matched_sha1` null, and records
`match_method` plus JSON `match_details` with game ID, candidate IDs, source and
catalog titles, corroborating facts, matcher version and platform-map checksum.
The explorer query includes match method, LaunchBox ID and resolution basis.
All links are recalculated on rebuild; LaunchBox is excluded from matching
corroboration to prevent self-reinforcing decisions. Full description text is
retained; value indexes use compact MD5 keys to avoid PostgreSQL B-tree size
limits for long descriptions.

`app.software_correction` likewise survives rebuilds and is the explorer's
working decision queue. Subjects and targets use complete release-content
signatures plus canonical system names rather than disposable numeric IDs.
The software layer consumes active rows after automatic assignment, records
`manual_content_correction` evidence, and removes any empty identity left by a
move. Reviewed decisions are promoted to `reference/software_corrections.csv`,
which derivation materializes as `ref.software_correction`; reference wins over
an equivalent working subject.

`catalog.software` is the consumer identity boundary. Unambiguous historical
SHA-1 matches create `recovered_legacy` identities scoped to the current
platform; unambiguous historical Parent/Clone groups can create or extend those
identities. A source-backed identity then cascades through an effective title
only when that title contains exactly one software anchor. Every remaining
release belongs to a visible `title_fallback` identity.
Detailed SHA-1, Parent/Clone, title-inheritance and candidate rows are temporary
build products. Only the accepted software membership and its compact
assignment basis are published. Durable human corrections remain in `app` and
promoted reference files.

The scoring cache includes every release, its additive score, dense rank within
software, and a JSON explanation. `release_iteration=latest` prefers the
highest explicit version where any exists for that software; otherwise it
compares revisions. The preferred view exposes unresolved top-score ties rather
than claiming the deterministic fallback is semantically unique.

## Temporary SQL relations

The remaining temporary relations are confined to one catalog transaction.
They cache a costly result only when several inserts or validations consume it,
such as content-signature matches or preference matches. They are never an
inter-layer handoff and are dropped at commit; all durable boundaries above are
normal tables.

## Recovery contract

`staging.rv_files`, reviewed integrated ZIPs, and version-controlled
reference/rule files can recreate everything. Database IDs are rebuild-local,
so maintained files identify systems and paths by source text rather than
generated IDs. A full derivation
invalidates the downstream catalog, which must then be rebuilt; routine selected
layers preserve unrelated upstream work.

Recovered older GameDB generations live alongside that active intake in
`staging.history_*`. They retain legacy software/release hierarchies, hashes,
Parent/Clone records, external mappings, synonyms, explicit match reviews, raw
workbook rows, and checksums for every imported artifact. These tables remain
evidence rather than canonical truth. The software layer currently consumes
unique legacy SHA-1 assignments and unambiguous Parent/Clone relationships;
external mappings, synonyms, and manual reviews remain candidates for later
reconciliation. Rerunning
`gamedb import-history` atomically refreshes only the history-owned tables.

## Arcade machine definitions and installation plans

`staging.arcade_source` records a versioned MAME listxml/classification input pair
and its hashes, together with explicit RomVault ROM/CHD DAT bindings.
`staging.arcade_machine` retains machine definitions, including parent/clone,
ROM-parent, device, BIOS, disk, sample and driver information. These inputs
survive derivation and catalog rebuilds.

The final `arcade` derivation layer emits ordinary source releases plus
`derived.arcade_release`, whose installation plan resolves the machine's
requirements against the matching version's inventory. A machine can have a
release even when all of its ROMs live in a parent archive. Shared dependencies
are not ordinary release-package memberships; the plan retains their physical
locations and required members explicitly. CHD content hashes and physical file
hashes remain distinct.

`catalog.arcade_release` publishes this plan for consumers. Its install signature
identifies a versioned machine definition, and is deliberately separate from
`catalog.release_content_signature`: neither a split archive nor a shared chip
establishes complete arcade software identity. MAME families use attributed
`parent_clone` software identities with `arcade_family` evidence. Support-only
BIOS/device packages remain inventory, and computer/console machines are excluded
from the Arcade catalog by the imported classification DAT.

The API validates physical availability before exposing a complete installation.
A streaming ZIP64 bundle preserves ROM ZIPs and puts selected CHDs in the selected
machine's directory. Missing dependencies produce an incomplete manifest and
HTTP 409 for bundle requests. Emulator support status is independent of content
completeness. See the README for the import command and API contract.

`staging.arcade_samples` retains a version-matched FBNeo samples DAT, its hash
and inventory DAT path. Sample dependencies resolve against `staging.rv_files`
CRC/size records and retain inventory SHA-1 values for installation verification.
Plans place sample ZIPs under `system/fbneo/samples`, with `systemDirectory=system`.
The samples refresh updates derived and published plans plus install-status facts;
rerun scoring afterward to include newly complete packages in preferred selection.


## LaunchBox image references and fallback media

`staging.launchbox_image` stores each GameImage source row, including game ID,
filename, type, region and raw fields (including CRC32). A row in
`staging.launchbox_image_import` marks a complete image import for a source ZIP.
No image binaries are stored in PostgreSQL.

The fallback joins published LaunchBox fact evidence to the exact source
snapshot/game ID, then fills empty software media slots. LaunchBox media records
carry source revision, XML row number, game ID and CRC32; software associations
use `launchbox_metadata` and record preferred release/region compatibility.
Libretro records and associations are unchanged. Repeating the fallback replaces
only its own projection, in one transaction.

`catalog.media_generation` stores a deterministic signature of selected media
paths, providers and matching attributes. This enters API catalog revisions so
artwork-only changes invalidate cached snapshots. Provider-local asset IDs are
not included, keeping identical media rebuilds cache-stable.
