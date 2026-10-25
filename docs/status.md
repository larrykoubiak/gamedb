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

The independent catalog, facts, title identity, software identity, metadata,
and scoring transactions were replayed from the derived contract.
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

The durable `default` user starts with global preferences plus an exact-system
Atari ST override. Translation roles are computed in software context: a
preferred-language translation is rewarded only when no unmodified release
matches a positively weighted language or region.

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
| Virtual Console distribution | -100 |
| Preferred-language translation fallback | +30 |
| Translation redundant with a preferred-locale original | -200 |
| Translation into a non-preferred language | -100 |
| Cracked Atari ST release | +10 |

The disposable score cache contains every release, including zero-score rows,
plus the matched-rule breakdown and a dense rank within its software. The
system scope and contextual translation roles keep these choices explicit and
independently tunable rather than relying on title-specific exceptions.

`app.user_preferred_release` provides one convenient row per user/software.
When top scores tie it selects the lowest rebuild-local release ID but reports
`top_score_tie_count` and `tie_broken`, so consumers can distinguish a genuine
unique winner from a deterministic fallback. Lower-ranked and tied releases
remain available in `app.user_release_score`.

## Libretro RDB staging

The pinned `libretro-database` revision
`12c21cf79f1e20eff6ac68b80875816c717d0a7a` contributes 146 compiled databases
and 738,241 source-faithful staging entries. Of those, 684,839 carry SHA-1 and
232,094 entries match the current inventory by exact SHA-1, reaching 226,407
catalog releases and 80,084 software identities.

Matched entries include 22,195 developer, 25,158 publisher, 24,179 genre,
7,121 franchise and 186,415 release-year claims. The raw typed records remain
in `staging.libretro_rdb_*`. A conservative exact-SHA-1 projection now exposes
76,658 ranked `catalog.software_fact` values for 19,999 software identities,
backed by 112,593 row-level evidence records. Conflicting developer, publisher,
genre and other software-oriented values remain visible as ranked candidates;
release-bound date, region, serial and ratings claims are not promoted there.

## LaunchBox candidate coverage

The first LaunchBox experiment imports the official Metadata.zip by SHA-256
(`d195ae79bf456b6d97fd8ab76a80147f53015e10a7a22253b23ce0781fd53d04`).
It contains 189,895 games and 71,478 alternate-name records (71,048 distinct
name/game pairs), with 126 explicit canonical-platform mappings.

Against the current 348,968 software identities, the conservative platform/title
report finds 53,987 unique candidates, 10,101 catalog-side ambiguities, 585
source-side ambiguities, 250,750 unmatched titles and 33,545 software identities
on unmapped platforms. Unique candidates could fill 46,524 missing descriptions,
37,292 developers, 37,773 publishers, 39,360 genres and 37,130 player counts.
These are potential field additions, not verified/promoted metadata.

The importer preserves source games, alternate names and platforms in
`staging.launchbox_*`. The read-only report uses exact normalized names, including
aliases, and blocks collisions in either direction within a canonical system.
The first report is under ignored `data/launchbox/report-reviewed/`; rerun the
report after a catalog rebuild. That initial report did not publish LaunchBox facts.

A second evidence pass (`platform-title-evidence-v2`) resolves 2,764 of the
10,686 ambiguous entries: 2,636 shared enrichment links and 128 source choices.
It requires date/company corroboration beyond a title match and leaves known
conflicts or tied evidence unresolved. The remaining ambiguities are 7,542 on
the catalog side and 380 on the source side. Catalog identities are not merged.
Together with the original unique matches, 56,751 entries now have selected
metadata candidates, potentially filling 48,841 descriptions, 39,247 developers,
39,810 publishers, 41,422 genres and 39,123 player counts. The current evidence
report is `data/launchbox/report-evidence-v2/`; its CSV records original status,
selected LaunchBox ID, supporting facts and the resolution rule for each entry.

The metadata layer now publishes these selections atomically with RDB facts.
The live rebuild contains 264,366 LaunchBox facts for 56,572 software identities
(179 selected records have none of the projected fields), alongside the unchanged
76,658 RDB facts for 19,999 identities. LaunchBox adds 54,439 descriptions,
51,774 developers, 52,837 publishers, 54,820 genres and 50,496 player-count
claims, including claims overlapping existing RDB fields. Exact-content RDB
claims rank first; competing values and source evidence remain available.

All published LaunchBox links were checked against the evidence-v2 report and
their staging source rows. The longest imported description (4,920 characters)
was verified untruncated, and both explorer fact queries return the new metadata.
The explorer assets label LaunchBox separately from RDB/hash-based evidence.

## LaunchBox artwork fallback

The retained ZIP contributes 1,343,990 image references in
`staging.launchbox_image`, with a completion marker per snapshot. The fallback
uses published LaunchBox game links and fills only missing Libretro media slots.
It added 74,119 associations across 34,873 software identities: 17,123 box fronts,
13,877 gameplay screenshots, 20,912 title screens and 22,207 clear logos.
All 180,218 existing Libretro associations were preserved exactly, verified with
a before/after selection signature.

LaunchBox image paths use `/media/launchbox/<kind>/<filename>`. The explorer
fetches only selected filenames from the fixed LaunchBox image origin, verifies
image bytes and CRC32, and persists successful downloads in the mounted
`data/media/launchbox` cache. Downloads are on demand; the whole image collection
is not mirrored. Source revision, game ID, XML row and CRC remain in catalog
media provenance. Launcher snapshots also include the media provider.

The media layer reapplies this fallback after Libretro selection. The
`catalog.media_generation` signature invalidates API ETags when artwork changes;
repeating an identical fallback preserves the signature. The explorer was rebuilt
and deployed on `larry-tower`, preserving the existing environment, database and
ROM mounts. Live checks passed for all four image types, the persistent cache,
API media provenance and conditional ETags. The Game Boy snapshot includes 364
LaunchBox artwork links. The full local test suite passes 168 tests.

## Rebuild workflow

There are now two explicit manifests. `derive.yml` orders schema, reference,
DAT, system, inventory, paths, names and source-release assembly. A destructive
full derivation requires `python -m gamedb derive --rebuild`; no-argument
execution is rejected. `--layers paths` re-resolves only paths, while
`--from-layer names` reinterprets stable names and reassembles releases.

`pipeline.yml` begins at that contract and orders catalog, facts, title
identity, software identity, software metadata, scoring and media. A scoring-only rebuild remains
isolated from derivation, inventory, paths, parsing, catalog facts, identity and metadata,
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

Core catalog, normalized facts, content identity, software identity and
software metadata have separate transactions and validation scripts. Each can
be rerun from its declared upstream state; rebuilding a layer removes its stale
downstream catalog caches.
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
