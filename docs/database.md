# Database model

GameDB is being rebuilt from the retained RomVault import. The schema boundaries
are intentionally simple:

| Schema | Responsibility |
| --- | --- |
| `staging` | Raw external input; currently only `rv_files` |
| `ref` | Maintained inputs loaded from version-controlled files |
| `derived` | Fully rebuildable parsing and classification results |
| `catalog` | Reconciled systems, titles, releases and files |

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

Database IDs are ordinary `bigint` identities and may change after a rebuild.
Reference and reconciliation files therefore use explicit source text, not IDs.

## Implemented rebuild layers

[`sql/rebuild/001_reference_and_dat.sql`](../sql/rebuild/001_reference_and_dat.sql)
currently creates:

| Table | Purpose |
| --- | --- |
| `ref.canonical_system` | Canonical systems loaded from `canonical_systems.csv` |
| `ref.system_mapping` | Complete per-romset source mapping loaded from `system_mappings.csv` |
| `derived.dat` | DAT identities parsed from `staging.rv_files` and resolved through the mapping |

[`scripts/rebuild_archive_names.py`](../scripts/rebuild_archive_names.py) then
parses distinct staged names and invokes
[`sql/rebuild/002_archive_names.sql`](../sql/rebuild/002_archive_names.sql) to create:

| Table | Purpose |
| --- | --- |
| `ref.tag_category` | Maintained classification categories loaded from `tag_categories.csv` |
| `derived.archive_name` | One parse per `(romset, original archive name)` |
| `derived.archive_name_record` | One or more ordered title records encoded by a name |
| `derived.archive_tag` | Ordered raw tags, separated source identifier/value, and rebuildable classifications |
| `derived.archive` | DAT/archive-name association with its staged row count |

[`sql/rebuild/003_catalog.sql`](../sql/rebuild/003_catalog.sql) creates the
consumer-facing projection:

| Table | Purpose |
| --- | --- |
| `catalog.system` | Canonical systems presented to consumers |
| `catalog.title` | System-scoped exact-title browse/search clusters |
| `catalog.release` | Source-faithful releases; no cross-region software grouping yet |
| `catalog.package` | DAT/archive provenance and archive-level parse state |
| `catalog.release_package` | Release/package membership and ordered media fields |
| `catalog.release_attribute` | Lossless classified and unknown tags with source provenance |
| `catalog.file` | RomVault paths, file names, sizes, hashes and verification state |

The catalog rebuild also loads `data/reference/path_mappings.csv` into
`ref.path_mapping` before resolving package paths.

The first title pass groups releases by exact `(system, display_title)`. A title
is only a browsing and metadata-search cluster, not an assertion that every
release is the same piece of software. Its explicit `cluster_key` is separate
from display text so reviewed overrides can later split same-name collisions
without depending on rebuild-local IDs.

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

The rebuild aborts if a mapping target is invalid, a staged DAT has no mapping,
or any generated record/tag/archive association is lost during loading. It never
modifies `staging.rv_files`.
