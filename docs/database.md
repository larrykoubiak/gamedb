# Database model and ownership

GameDB has one retained input, one interpreted source model, and one disposable
consumer model. The boundaries are ownership boundaries, not just naming
conventions.

| Schema | Owner | Responsibility |
| --- | --- | --- |
| `staging` | external intake | Untouched RomVault rows and immutable historical-source snapshots |
| `ref` | deriver | Version-controlled mappings and vocabularies |
| `derived` | deriver | Stable inventory plus source-faithful semantic interpretation |
| `catalog` | catalog builder | Accepted browse facts: software, releases, packages and files |
| `app` | application | Durable users/preferences plus disposable user score projections |

```text
                         DERIVATION PACKAGE
staging.rv_files ──┬──► DAT identity ─► system resolution
                   ├──► package/file inventory ─► resolved package paths
reference files ───┴──► name parser/classifier
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

`staging.rv_files` plus version-controlled reference/rule files can recreate
everything. Database IDs are rebuild-local, so maintained files identify
systems and paths by source text rather than generated IDs. A full derivation
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
