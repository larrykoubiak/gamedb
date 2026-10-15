# Database model

GameDB is being rebuilt from the retained RomVault import. The schema boundaries
are intentionally simple:

| Schema | Responsibility |
| --- | --- |
| `staging` | Raw external input; currently only `rv_files` |
| `ref` | Maintained inputs loaded from version-controlled files |
| `derived` | Fully rebuildable parsing and classification results |
| `catalog` | Reconciled systems, titles, releases and files |
| `app` | Durable local users and personal preferences |

The recovery contract is:

```text
staging + data/reference
          ↓
       derived
          ↓
    reconciliation
          ↓
       catalog
```

The `app` schema is deliberately outside that destructive rebuild path.
`app.app_user` and `app.user_preference` survive catalog resets; the generated
score cache lives under `catalog` and is recreated from them.

Database IDs are ordinary `bigint` identities and may change after a rebuild.
Reference and reconciliation files therefore use explicit source text, not IDs.

## Executable rebuild layers

[`pipeline.yml`](../pipeline.yml) declares the complete ordered rebuild. Its
`reference` layer, implemented by
[`010_reference_and_dat.sql`](../sql/layers/reference/010_reference_and_dat.sql),
creates:

| Table | Purpose |
| --- | --- |
| `ref.canonical_system` | Canonical systems loaded from `canonical_systems.csv` |
| `ref.system_mapping` | Complete per-romset source mapping loaded from `system_mappings.csv` |
| `derived.dat` | DAT identities parsed from `staging.rv_files` and resolved through the mapping |

The `archive_names` layer has one `ArchiveNamesStep`. It parses and classifies
distinct staged names, then uses
[`010_load.sql`](../sql/layers/archive_names/010_load.sql) to create:

| Table | Purpose |
| --- | --- |
| `ref.tag_category` | Maintained classification categories loaded from `tag_categories.csv` |
| `derived.archive_name` | One parse per `(romset, original archive name)` |
| `derived.archive_name_record` | One or more ordered title records encoded by a name |
| `derived.archive_tag` | Ordered raw tags, separated source identifier/value, and rebuildable classifications |
| `derived.archive` | DAT/archive-name association with its staged row count |

The `catalog`, `facts`, and `identity` layers each run as an independent
transaction. Catalog builds the source-faithful core and files, facts projects
normalized attributes with evidence, and identity reconciles titles by exact
content. Together they create the consumer-facing projection:

| Table | Purpose |
| --- | --- |
| `catalog.system` | Canonical systems presented to consumers |
| `catalog.title` | System-scoped exact-title browse/search clusters |
| `catalog.title_alias` | Non-representative titles mapped to an exact-content component representative |
| `catalog.title_content_match` | Direct same-system complete-release SHA-1 matches between titles |
| `catalog.release` | Source-faithful releases; no cross-region software grouping yet |
| `catalog.package` | DAT/archive provenance and archive-level parse state |
| `catalog.package_content_signature` | Complete SHA-1 multiset fingerprints for unshared packages |
| `catalog.release_package` | Release/package membership and ordered media fields |
| `catalog.release_content_signature` | Complete fingerprints across every package in an eligible release |
| `catalog.release_fact` | Harmonized, deduplicated release-level features |
| `catalog.release_fact_evidence` | Package/tag evidence for normalized facts |
| `catalog.release_source_attribute` | View of lossless source tags and classifications |
| `catalog.file` | RomVault paths, file names, sizes, hashes and verification state |

The catalog rebuild also loads `data/reference/path_mappings.csv` into
`ref.path_mapping` before resolving package paths.

### Transaction-local working tables

Names beginning with `_catalog_`, plus `_preference_match`, are temporary
working relations, not another data layer. PostgreSQL drops them when their
layer transaction commits. They materialize an expensive intermediate result
when more than one later statement needs it; a CTE would exist for only one
statement and would require either repeating the query or folding several
independently validated writes into one large statement.

| Working relation | Why it is materialized |
| --- | --- |
| `_catalog_candidate`, `_catalog_preliminary`, `_catalog_member` | Turn parsed records into stable release groups, then reuse that membership while inserting titles, releases, and release-package links and validating their counts |
| `_catalog_source_fact` | Reuse the same normalized tag expansion for deduplicated facts and their many evidence links |
| `_catalog_title_content_match` | Freeze exact hash matches for both persisted evidence and transitive component construction |
| `_catalog_title_component`, `_catalog_title_component_summary`, `_catalog_title_representative` | Reuse recursive connected components while selecting and validating one representative and all aliases |
| `_preference_match` | Reuse preference matches while compiling score totals and JSON explanations |

CTEs remain preferable for one-consumer transformations. These temporary tables
are intentionally scoped to one declared pipeline layer and are never an input
to a later layer.

The first title pass groups releases by exact `(system, display_title)`. A title
is only a browsing and metadata-search cluster, not an assertion that every
release is the same piece of software. Its explicit `cluster_key` is separate
from display text so reviewed overrides can later split same-name collisions
without depending on rebuild-local IDs.

A second, non-destructive reconciliation pass evaluates content before names.
It fingerprints the complete multiset of ROM SHA-1s in an unshared package, then
the complete package set of each eligible release. Same-system titles connected
by one or more exact release fingerprints form transitive content components;
case, spacing, punctuation and other name differences do not block a match.
Each component receives one deterministic representative, favoring No-Intro and
then broader release coverage. Shared/compound packages, incomplete SHA-1 sets
and unmatched titles stay independent. Score ranking resolves component members,
so every linked release competes under one displayed title; the original titles,
releases, names, packages and files remain unchanged.

`catalog.package.source_tree_path` preserves the RomVault archive path.
`catalog.package.resolved_path` applies the longest prefix from
`data/reference/path_mappings.csv` and is null when no host mapping is maintained.
The member within an archive remains separately available as
`catalog.file.member_path`; it is not mistaken for a directly accessible host
filesystem path.

Automatic media grouping is deliberately narrow. Records must come from the
same DAT and have the same title and identical non-media tags. Only their one
structured media tag may differ. Duplicate part/side slots are split and marked
`media_ambiguous`; missing sets remain visible as `media_singleton` or
`media_grouped` rather than being silently treated as complete.

Release facts are a conservative consumer projection of explicit classifier
output. Region and language arrays become individual facts, canonical `code`
and source-preserving `text` fields become key/value facts, and repeated facts
across media packages are deduplicated. Evidence rows retain the exact source
package and `derived.archive_tag`. The catalog also supplies computed
`source_collection`, `media_status` and `review_status` facts. Free-form and
unclassified tags remain available through `catalog.release_source_attribute`;
the release-fact pass itself performs no language inference or preference
scoring. Explicit TOSEC translation descriptors contribute their parsed target
language and patch version in addition to `dump_modification=translated`.

The `scoring` layer executes separate preference, score-generation, and
preferred-release SQL files. It creates or preserves:

| Table | Purpose |
| --- | --- |
| `app.app_user` | Durable local user identities |
| `app.user_preference` | Enabled additive fact matches and relative scoring rules |
| `catalog.user_score_generation` | Cache timestamp and preference signature |
| `catalog.user_release_score` | Disposable scores, title-relative ranks and JSON explanations |
| `catalog.user_preferred_release` | One highest-scoring release per user/title with tie metadata |

Exact preferences match one deduplicated release fact and contribute their
configured score once. The relative `latest` operator uses natural numeric
ordering. The virtual `release_iteration` preference compares explicit version
facts when any exist within the resolved title, otherwise explicit revisions;
releases with neither receive no iteration bonus. Cache generation includes
zero-score releases, uses dense title-relative ranks and replaces the old cache
atomically. The preferred-release view uses `release_id` only as a deterministic
fallback among equal top scores and exposes both `top_score_tie_count` and
`tie_broken`; it does not claim that a scoring tie has been semantically resolved.

The rebuild aborts if a mapping target is invalid, a staged DAT has no mapping,
or any generated record/tag/archive association is lost during loading. It never
modifies `staging.rv_files`.
