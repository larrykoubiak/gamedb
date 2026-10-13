# Project status and handoff

Last verified against the retained RomVault export on **2026-10-13**. Counts in
this document describe that export; they are observations, not schema invariants.

## Current milestone

The first exact-title clustering and normalized release-fact passes are
complete. `staging.rv_files` is the only retained raw database input. Everything
else can be recreated from staging and the maintained files under
`data/reference/` using the five commands in the root README. Durable local
users and preferences under `app` survive those rebuilds.

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
| Catalog releases | 908,828 |
| Normalized release facts | 5,395,078 |
| Release-fact evidence rows | 2,855,950 |
| Cached scores for the default user | 908,828 |
| Catalog packages | 973,417 |
| Catalog files | 1,359,794 |

The catalog rebuild and all 44 parser/classifier tests passed at this milestone.
Every release belongs to one title cluster. All four supported collection roots
in `path_mappings.csv` resolve to the local Synology mount; every current package
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
908,828 releases form 341,736 clusters.

Same-name collisions remain possible—for example, independently published games
called `Tetris`. `catalog.title.cluster_key` is therefore separate from
`display_title`, and title display text is not unique within a system. A future
reviewed override can split a same-name cluster without changing visible text or
depending on rebuild-local IDs.

## Release facts

The first normalization pass contains 2,668,594 explicit source-tag facts and
2,726,484 computed catalog facts. Explicit facts cover 908,792 releases; all
908,828 releases have computed `source_collection`, `media_status` and
`review_status` facts. Multivalued source claims are expanded—for example,
66,097 releases produce 89,876 individual language facts—and repeated claims
across packages are collapsed while retaining separate evidence rows.

The pass is deliberately conservative. Free-form `additional`, unclassified
and media-component tags remain available through
`catalog.release_source_attribute`. No regional language defaults, translation
interpretation, revision ordering, preference weights or release scores are
generated in the fact layer itself.

## Preference scoring

The durable `default` user currently has five enabled seed preferences:

| Preference | Score |
| --- | ---: |
| Explicit English language | +100 |
| Latest fully numeric release date within the title | +20 |
| Source-verified dump | +30 |
| Hacked dump modification | -200 |
| No-Intro source collection | +50 |

The disposable score cache contains every release, including zero-score rows,
plus the matched-rule breakdown and a dense rank within its title. Scores
currently range from -200 to 170. Of 341,736 titles, 243,562 have one top-ranked
release and 98,174 retain a tie. Preferences are illustrative rather than a
claim that the weights are final.

`catalog.user_preferred_release` provides one convenient row per user/title.
When top scores tie it selects the lowest rebuild-local release ID but reports
`top_score_tie_count` and `tie_broken`, so consumers can distinguish a genuine
unique winner from a deterministic fallback. Lower-ranked and tied releases
remain available in `catalog.user_release_score`.

## Next architectural step

Build a read-only visual explorer showing ranked releases, score breakdowns and
their underlying facts/evidence. It should also expose the current preference
rows so the seed weights can be evaluated hands-on before inference rules such
as region-to-language defaults are introduced.

Only after real same-name collisions are identified should a maintained
split-override layer be added. Overrides should use explicit source
text/provenance and stable cluster keys, never generated title or release IDs.
Metadata ingestion can later cache source responses and external IDs and use
them as evidence for reviewed splits or eventual cross-title grouping.

An eventual `software` entity can sit above titles and express cross-regional or
alternate-title equivalence such as *Bare Knuckle* and *Streets of Rage*. Do not
make canonical display text the identity of that entity.

## Known limitations and deferred work

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
