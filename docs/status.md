# Project status and handoff

Last verified against the retained RomVault export on **2026-10-16**. Counts in
this document describe that export; they are observations, not schema invariants.

## Current milestone

The standalone derivation cutover is complete. `gamedb.derive` now owns `ref`
and `derived`, including stable package/file/path inventory and a one-pass Python
interpretation of source titles, tags, assertions, media and releases. The SQL
catalog builder consumes that relational contract; it no longer parses names,
reopens classifier JSON, reloads inventory, or resolves paths. Local users and
preferences under `app` survive catalog rebuilds.

The verified build contains:

| Object | Rows |
| --- | ---: |
| Canonical systems | 453 |
| Reviewed source-system mappings | 593 |
| DATs | 2,915 |
| Distinct parsed archive names | 794,395 |
| Parsed archive-name records | 795,244 |
| Parsed tags | 2,632,740 |
| Typed assertions | 2,362,584 |
| Typed media rows | 161,703 |
| Exact-title clusters | 342,084 |
| Complete package content signatures | 969,973 |
| Complete release content signatures | 904,520 |
| Direct cross-title content matches | 4,013 |
| Titles mapped to content representatives | 3,211 |
| Effective preferred-title clusters | 338,873 |
| Recovered software identities (platform-scoped) | 7,969 |
| Parent/Clone software identities | 2,995 |
| Title-fallback software identities | 326,339 |
| Exact-SHA-1 software assignments | 18,425 |
| Parent/Clone software assignments | 6,132 |
| Unique-title inherited assignments | 18,492 |
| Catalog releases | 909,607 |
| Normalized release facts | 5,407,158 |
| Release-fact evidence rows | 2,865,856 |
| Cached scores for the default user | 909,607 |
| Derived packages | 976,597 |
| Derived files | 1,364,237 |

The independent catalog, facts, title identity, software identity, and scoring
transactions were replayed from the derived contract, and all 81 tests pass.
Every release belongs to one title cluster and exactly one software identity.
All five supported collection roots in
`path_mappings.csv` resolve to the local Synology mount; every current package
has a `resolved_path`. The 2,400 packages whose source names are deliberately
ignored remain visible in inventory but correctly produce no parse or release.

## Terminology

The current consumer hierarchy is:

```text
System
  └── Software
        ├── Title spelling(s)
        └── Release
              └── Package
                    └── File
```

- A **title** is a system-scoped, exact-title browse and metadata-search cluster.
  It is not proof that all linked releases describe the same software.
- **Software** is the platform-specific playable product across title spellings
  and releases. Recovered associations and exact same-title grouping are
  accepted by default; discovered mistakes become explicit corrections.
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
filesystem paths. `derived.package_path.resolved_path` identifies the archive on
the host; `derived.file.member_path` identifies the member inside it.

## Media grouping

Media grouping is intentionally conservative. Records are combined only within
one DAT when the title and every non-media tag match exactly and only one
structured media tag differs.

| Status | Releases |
| --- | ---: |
| Complete numeric media sets | 14,063 |
| Grouped but not provably complete | 34,568 |
| Numbered-media singletons | 49,873 |
| Ambiguous duplicate slots, left separate | 21 |
| Standalone releases | 811,082 |

Numeric parts, zero-padded parts, alphabetic discs and tape sides retain their
ordering. Future playlist generation should use `catalog.release_package` and
must keep region/version variants separate.

## Title grouping

The first pass groups by exact `(system, display_title)`. On the current TOSEC
data, 841,867 releases form 308,581 exact-title clusters; 110,398 clusters
contain multiple releases and the largest contains 486. Across all collections,
909,607 releases form 342,084 clusters. A non-destructive exact-content pass
first fingerprints the complete SHA-1 multiset of each unshared package and then
the complete package set of each eligible release. Exact same-system release
matches connect 6,265 titles into 3,054 transitive content components. The pass
maps 3,211 non-representative titles, supported by 4,013 direct release-pair
matches, leaving 338,873 effective clusters for preference ranking. Names do not
constrain an exact-content match. Incomplete hashes and compound/shared packages
remain excluded from identity evidence.

Same-name collisions remain possible—for example, independently published games
called `Tetris`. `catalog.title.cluster_key` is therefore separate from
`display_title`, and title display text is not unique within a system. A future
reviewed override can split a same-name cluster without changing visible text or
depending on rebuild-local IDs.

## Release facts

The first normalization pass contains 2,678,337 explicit source-tag facts and
2,728,821 computed catalog facts. Explicit facts cover 909,571 releases; all
909,607 releases have computed `source_collection`, `media_status` and
`review_status` facts. Multivalued source claims are expanded—for example,
72,861 releases produce 96,763 individual language facts—and repeated claims
across packages are collapsed while retaining separate evidence rows.

TOSEC translation flags preserve their explicit target language and patch
version. For example, `[tr en v1.3 Dejap]` contributes `language=en`,
`version=1.3` and `dump_modification=translated`, all linked to the original tag.

The English Translations/Maybe-Intro source contributes 32 DATs, 810 packages,
2,066 files and 779 grouped releases. Its 780 playable names parse without
review or unclassified tags; 30 documentation archives remain inventory-only.
Playable member names are also interpreted separately: for archives carrying
Maybe-Intro's `[n]` localized-title marker, the retained member title is treated
as original-title evidence. Of 342 such releases with one unambiguous member
title, 139 currently resolve to exactly one source-backed software identity.
For example, `Tenchi Muyou! - The Game` joins the recovered
`Tenchi Muyou! - Game Hen` software through its member filename; the associated
readme only calls the game `Tenchi Muyo RPG` and is not used as title evidence.
For Bahamut Lagoon, its clean v1.3 translation now ties the TOSEC v1.3 release
at +60 and wins the deterministic fallback, while its explicit Emulation Hack
variant scores -140.

The pass is deliberately conservative. Free-form `additional`, unclassified
and media-component tags remain available through
the derived source tables. No regional language defaults, preference
weights or release scores are generated in the fact layer itself.

## Working software corrections

The local explorer can move a signed release to an existing same-system
software or separate it into a manual identity. The exception is stored in
`app.software_correction`; saving runs the software and scoring layers before
the UI refreshes. Complete release signatures move identical source
occurrences together. Missing subjects, ambiguous targets, cross-system
targets, and correction chains/cycles stop the software transaction.

Reviewed active decisions can be promoted in one pass with
`python -m gamedb promote-corrections`. Promotion writes the deterministic
maintained CSV, updates `ref.software_correction`, and retains the working row
with `promoted` status for audit.

## Preference scoring

The durable `default` user currently has nine enabled seed preferences:

| Preference | Score |
| --- | ---: |
| US region | +100 |
| Explicit English language | +40 |
| Latest explicit version, or revision when no versions exist | +20 |
| Source-verified dump | +30 |
| Any explicit non-standard release status | -500 |
| Any TOSEC demo classification | -500 |
| Alternate dump (`[a]`, `[a2]`, …) | -50 |
| Hacked dump modification | -200 |
| No-Intro source collection | +50 |

The disposable score cache contains every release, including zero-score rows,
plus the matched-rule breakdown and a dense rank within its software. Scores
currently range from -1,030 to 210. Of 337,225 software identities, 257,336 have
one top-ranked release and 79,889 retain a tie. Preferences are illustrative
rather than a claim that the weights are final.

`app.user_preferred_release` provides one convenient row per user/software.
When top scores tie it selects the lowest rebuild-local release ID but reports
`top_score_tie_count` and `tie_broken`, so consumers can distinguish a genuine
unique winner from a deterministic fallback. Lower-ranked and tied releases
remain available in `app.user_release_score`.

## Rebuild workflow

There are now two explicit manifests. `derive.yml` orders schema, reference,
DAT, system, inventory, paths, names and source-release assembly. A destructive
full derivation requires `python -m gamedb derive --rebuild`; no-argument
execution is rejected. `--layers paths` re-resolves only paths, while
`--from-layer names` reinterprets stable names and reassembles releases.

`pipeline.yml` begins at that contract and orders catalog, facts, title
identity, software identity, scoring and media. A scoring-only rebuild remains
isolated from derivation, inventory, paths, parsing, catalog facts, and identity,
but does not refresh preference-aware media. Use `python -m gamedb rebuild
--from-layer scoring` to refresh both scores and artwork associations.

Multi-file SQL steps report file-level progress and elapsed time while retaining
one database transaction. Explorer queries live separately under
`sql/queries/explorer`; `CatalogRepository` owns query binding and execution,
while `gamedb.explorer.server` owns HTTP transport and static assets.

Deriver, catalog builder and explorer code live in separate `gamedb.derive`,
`gamedb.catalog`, and `gamedb.explorer` packages. The Dockerfile provides matching
`deriver`, `catalog-builder`, and `explorer` targets with only their own runtime
dependencies and inputs.

The deployment Compose stack also owns its PostgreSQL 16 service. It preserves
database state in `./data/pgdata`; all application containers connect over the
Compose network as `db:5432`, while port 9876 remains available for optional
host access. On `larry-tower`, that bind mount is the existing
`/srv/docker/gamedb/data/pgdata` database rather than a new Docker volume.
The optional `public` profile retains the existing Cloudflare tunnel, and the
explorer has a `web` network alias compatible with its former origin name.
Workstation development uses the separate `compose.dev.yaml`: it contains no
database service and passes the local `.env` connection directly to the local
explorer and one-shot tools. Setting `COMPOSE_FILE=compose.dev.yaml` locally
keeps the usual `docker compose` commands while targeting the tower database.

Core catalog, normalized facts, content identity, and software identity have
separate transactions and validation scripts. Each can be rerun from its
declared upstream state; rebuilding a layer removes its stale downstream
catalog caches.
Temporary tables remain only as private scratch state inside one layer. The
deriver uses focused parser, extractor, spool writer, persistence, and pipeline
classes instead of the former procedural archive-name loader.

## Next identity step

Use the local explorer to evaluate preferred releases and seed weights
hands-on. It provides a manufacturer/system tree, in-system title filtering,
paginated preferred releases, normalized facts, score explanations and explicit
tie counts. Each software row expands to show all losing releases, source package
names and complete file hashes. Run it with `python -m gamedb serve`; it loads
missing PostgreSQL connection settings from the project `.env` automatically.

The catalog now overlays non-destructive exact-content components. Any
same-system titles connected by complete package/release SHA-1 fingerprints are
ranked together, even when their source names differ. Transitive connectivity
allows one source title containing several regional releases to join several
source-specific spellings. Representative selection favors No-Intro for display;
it does not affect identity evidence. The original exact-title clusters and all
source releases remain available.

The first non-destructive software tier now exists above source-title clusters.
It recovers 7,957 historical software records as 7,969 platform-scoped current
identities and assigns 18,425 releases through exact SHA-1. Parent/Clone adds
2,995 identities and 6,132 release assignments. Unique anchored titles safely
inherit another 18,492 releases; titles with competing anchors stop and remain
reviewable. The remaining 866,558 releases retain title-based behavior through
326,339 explicit fallback identities.

The next tier is graded reconciliation: Parent/Clone relationships, reviewed
external identifiers, recovered positive/negative match decisions and explicit
maintained overrides. Normalized or fuzzy name similarity may generate review
candidates, but must not silently establish identity. Reviewed mappings and
splits must use stable source evidence, never rebuild-local IDs.

Translation scoring also needs one more level of structure. Translation project
or team identity should be established before comparing versions: `v1.3` from
one project is not necessarily newer or preferable to `v1.2` from another.
Release ranking can then select among releases attached to the same software,
while retaining project/team preference as an explicit future user rule.

Observed cases in the explorer can seed these mappings and reveal genuine
same-name collisions. Metadata ingestion can later cache source responses and
external IDs and contribute further evidence; it need not replace the current
source-faithful title and release layers.

## Known limitations and deferred work

- Unclassified tags are retained losslessly rather than discarded: 3,359
  No-Intro, 671 Redump, 6,427 TOSEC and 33 TOSEC-ISO tag occurrences remain in
  the current derived data. Classification can be improved and replayed later.
- Metadata scraping has not started. Cache source responses and external IDs;
  use them as evidence for grouping rather than requiring perfect grouping first.
- Recovered Parent/Clone DAT relationships now contribute only when both the
  release and group are unambiguous. Six conflicting groups and 115 releases
  mapping to multiple groups remain review candidates. TOSEC has no equivalent
  general relationship source.
- Broader cross-region reconciliation, attributed/localized names,
  translation-project identity, metadata conflict handling, emulator selection,
  extraction and `.m3u` generation are not implemented.
- Ordinary `bigint` identity values are intentionally rebuild-local. Maintained
  reference or override files must use explicit source text, never database IDs.

This is a personal, replayable database rather than a mass-deployment migration
system. Prefer a clear rebuild and small reviewed patch files over preserving
generated identities or adding speculative abstraction.
