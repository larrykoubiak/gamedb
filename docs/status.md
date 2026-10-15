# Project status and handoff

Last verified against the retained RomVault export on **2026-10-15**. Counts in
this document describe that export; they are observations, not schema invariants.

## Current milestone

The first exact-title clustering and normalized release-fact passes are
complete. `staging.rv_files` is the only retained raw database input. Everything
else can be recreated from staging and the maintained files under
`data/reference/` through the ordered workflow in `pipeline.yml`. Individual
layers can be planned or selected without replaying unchanged upstream work.
Local users and preferences under `app` survive catalog rebuilds.

The verified build contains:

| Object | Rows |
| --- | ---: |
| Canonical systems | 453 |
| Reviewed source-system mappings | 561 |
| DATs | 2,883 |
| Distinct parsed archive names | 793,615 |
| Parsed archive-name records | 794,464 |
| Parsed tags | 2,630,601 |
| Exact-title clusters | 341,736 |
| Complete package content signatures | 969,193 |
| Complete release content signatures | 903,741 |
| Direct cross-title content matches | 3,887 |
| Titles mapped to content representatives | 3,102 |
| Effective preferred-title clusters | 338,634 |
| Catalog releases | 908,828 |
| Normalized release facts | 5,401,210 |
| Release-fact evidence rows | 2,862,233 |
| Cached scores for the default user | 908,828 |
| Catalog packages | 973,417 |
| Catalog files | 1,359,794 |

The independent catalog, facts, identity, and scoring transactions were replayed
in order from the existing derived layer, and all 64
parser/classifier/explorer/workflow tests passed at this milestone. Every
release belongs to one title cluster. All four supported collection roots in
`path_mappings.csv` resolve to the local Synology mount; every current package
has a `resolved_path`.

## Terminology

The current consumer hierarchy is:

```text
System
  └── Title
        └── Release
              └── Package
                    └── File
```

- A **title** is a system-scoped, exact-title browse and metadata-search cluster.
  It is not proof that all linked releases describe the same software.
- A **release** is currently a source-faithful title/variant: system, title,
  region, language, version, revision, dump state and other source claims have
  not been reconciled into a canonical game identity.
- A **release fact** is a harmonized, deduplicated key/value feature derived
  from an explicit classified source tag or catalog structure. Evidence links
  source-derived facts back to every supporting package and original tag.
- A **package** is one stored source archive, normally a ZIP. It is kept separate
  because one release may use several disc packages, one package may represent
  several compound TOSEC records, and a CD package may contain many files.
  Packages shared by several releases are retained but excluded from automatic
  identity evidence.
- A **file** is a member of a package with its source locator, member path, size,
  hashes and verification state.

RomVault member paths such as `archive.zip/game.rom` are not treated as physical
filesystem paths. `catalog.package.resolved_path` identifies the archive on the
host; `catalog.file.member_path` identifies the member inside it.

## Media grouping

Media grouping is intentionally conservative. Records are combined only within
one DAT when the title and every non-media tag match exactly and only one
structured media tag differs.

| Status | Releases |
| --- | ---: |
| Complete numeric media sets | 14,063 |
| Grouped but not provably complete | 34,567 |
| Numbered-media singletons | 49,878 |
| Ambiguous duplicate slots, left separate | 16 |
| Standalone releases | 810,304 |

Numeric parts, zero-padded parts, alphabetic discs and tape sides retain their
ordering. Future playlist generation should use `catalog.release_package` and
must keep region/version variants separate.

## Title grouping

The first pass groups by exact `(system, display_title)`. On the current TOSEC
data, 841,867 releases form 308,581 exact-title clusters; 110,398 clusters
contain multiple releases and the largest contains 486. Across all collections,
908,828 releases form 341,736 clusters. A non-destructive exact-content pass
first fingerprints the complete SHA-1 multiset of each unshared package and then
the complete package set of each eligible release. Exact same-system release
matches connect 6,061 titles into 2,959 transitive content components. The pass
maps 3,102 non-representative titles, supported by 3,887 direct release-pair
matches, leaving 338,634 effective clusters for preference ranking. Names do not
constrain an exact-content match. Incomplete hashes and compound/shared packages
remain excluded from identity evidence.

Same-name collisions remain possible—for example, independently published games
called `Tetris`. `catalog.title.cluster_key` is therefore separate from
`display_title`, and title display text is not unique within a system. A future
reviewed override can split a same-name cluster without changing visible text or
depending on rebuild-local IDs.

## Release facts

The first normalization pass contains 2,674,726 explicit source-tag facts and
2,726,484 computed catalog facts. Explicit facts cover 908,792 releases; all
908,828 releases have computed `source_collection`, `media_status` and
`review_status` facts. Multivalued source claims are expanded—for example,
66,097 releases produce 89,876 individual language facts—and repeated claims
across packages are collapsed while retaining separate evidence rows.

TOSEC translation flags preserve their explicit target language and patch
version. For example, `[tr en v1.3 Dejap]` contributes `language=en`,
`version=1.3` and `dump_modification=translated`, all linked to the original tag.

The pass is deliberately conservative. Free-form `additional`, unclassified
and media-component tags remain available through
`catalog.release_source_attribute`. No regional language defaults, preference
weights or release scores are generated in the fact layer itself.

## Preference scoring

The durable `default` user currently has six enabled seed preferences:

| Preference | Score |
| --- | ---: |
| US region | +100 |
| Explicit English language | +40 |
| Latest explicit version, or revision when no versions exist | +20 |
| Source-verified dump | +30 |
| Hacked dump modification | -200 |
| No-Intro source collection | +50 |

The disposable score cache contains every release, including zero-score rows,
plus the matched-rule breakdown and a dense rank within its title. Scores
currently range from -200 to 210. Of 338,634 effective titles, 240,573 have one
top-ranked release and 98,061 retain a tie. Preferences are illustrative rather
than a claim that the weights are final.

`catalog.user_preferred_release` provides one convenient row per user/title.
When top scores tie it selects the lowest rebuild-local release ID but reports
`top_score_tie_count` and `tie_broken`, so consumers can distinguish a genuine
unique winner from a deterministic fallback. Lower-ranked and tied releases
remain available in `catalog.user_release_score`.

## Rebuild workflow

`pipeline.yml` is the executable table of contents for the project. It orders
the reset, reference, archive-name, catalog, facts, identity, and scoring layers
and names every step and SQL file. Concrete `RunSqlStep` and `ArchiveNamesStep`
classes execute those declarations. `python -m gamedb rebuild --plan` explains
the complete story; `--layers`, `--from-layer`, and `--through-layer` select
development subsets. A complete run remains reproducible from staging and
version-controlled rules rather than preserved generated state.

Multi-file SQL steps report file-level progress and elapsed time while retaining
one database transaction. Explorer queries live separately under
`sql/queries/explorer`; `CatalogRepository` owns query binding and execution,
while `gamedb.explorer.server` owns HTTP transport and static assets.

Loader and explorer code now live in separate `gamedb.load` and
`gamedb.explorer` packages. The Dockerfile provides matching `loader` and
`explorer` targets; the explorer target does not install loader dependencies or
copy rebuild SQL/reference inputs.

Core catalog, normalized facts, and content identity now have separate
transactions and validation scripts. Each can be rerun from its declared
upstream state; rebuilding a layer removes its stale downstream catalog caches.
Temporary tables remain only as private scratch state inside one layer. The
archive-name rebuild is also divided into source, CSV writer, loader, and
orchestrator classes instead of procedural helper functions.

## Next architectural step

Use the local read-only explorer to evaluate preferred releases and seed weights
hands-on. It provides a manufacturer/system tree, in-system title filtering,
paginated preferred releases, normalized facts, score explanations and explicit
tie counts. Each title row expands to show all losing releases, source package
names and complete file hashes. Run it with `python -m gamedb serve`; it loads
missing PostgreSQL connection settings from the project `.env` automatically.

The catalog now overlays non-destructive exact-content components. Any
same-system titles connected by complete package/release SHA-1 fingerprints are
ranked together, even when their source names differ. Transitive connectivity
allows one source title containing several regional releases to join several
source-specific spellings. Representative selection favors No-Intro for display;
it does not affect identity evidence. The original exact-title clusters and all
source releases remain available.

Observed cases can now guide the next conservative reconciliation tier for
unmatched names, plus scoring improvements or inference rules such as
region-to-language defaults. Name-based candidates should remain reviewable and
must not be treated with the same certainty as exact content matches.

Only after real same-name collisions are identified should a maintained
split-override layer be added. Overrides should use explicit source
text/provenance and stable cluster keys, never generated title or release IDs.
Metadata ingestion can later cache source responses and external IDs and use
them as evidence for reviewed splits or eventual cross-title grouping.

An eventual `software` entity can sit above titles and express cross-regional or
alternate-title equivalence such as *Bare Knuckle* and *Streets of Rage*. Do not
make canonical display text the identity of that entity.

## Known limitations and deferred work

- The retained staging export contains an `English Translations` collection
  with 32 DATs, 810 distinct archive names and 2,066 file rows. It is not yet
  included in `derived` or `catalog`. It needs its own system mappings and
  archive-name profile for `[T-En by ...]`, `Hack+T-En`, `Text Hack`, `[n]` and
  `[i]`; 30 documentation ZIPs should be excluded from playable packages.
- Unclassified tags are retained losslessly rather than discarded: 3,359
  No-Intro, 671 Redump, 6,427 TOSEC and 33 TOSEC-ISO tag occurrences remain in
  the current derived data. Classification can be improved and replayed later.
- Metadata scraping has not started. Cache source responses and external IDs;
  use them as evidence for grouping rather than requiring perfect grouping first.
- No-Intro Parent/Clone DAT relationships are deferred. They can be imported
  directly and matched to owned ROMs by SHA-1/MD5/CRC and size without rescanning
  RomVault. TOSEC has no equivalent general relationship source.
- Cross-region software grouping, canonical titles, metadata conflict handling,
  emulator selection, extraction and `.m3u` generation are not implemented.
- Ordinary `bigint` identity values are intentionally rebuild-local. Maintained
  reference or override files must use explicit source text, never database IDs.

This is a personal, replayable database rather than a mass-deployment migration
system. Prefer a clear rebuild and small reviewed patch files over preserving
generated identities or adding speculative abstraction.
