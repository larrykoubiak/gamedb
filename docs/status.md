# Project status and handoff

Last verified against the retained RomVault export on **2026-10-13**. Counts in
this document describe that export; they are observations, not schema invariants.

## Current milestone

The first rewrite pass is complete. `staging.rv_files` is the only retained raw
database input. Everything else can be recreated from staging and the maintained
files under `data/reference/` using the four commands in the root README.

The verified build contains:

| Object | Rows |
| --- | ---: |
| Canonical systems | 453 |
| Reviewed source-system mappings | 561 |
| DATs | 2,883 |
| Distinct parsed archive names | 793,615 |
| Parsed archive-name records | 794,464 |
| Parsed tags | 2,630,601 |
| Catalog releases | 908,828 |
| Catalog packages | 973,417 |
| Catalog files | 1,359,794 |

The clean rebuild and all 44 parser/classifier tests passed at this milestone.
All four supported collection roots in `path_mappings.csv` resolve to the local
Synology mount; every current package has a `resolved_path`.

## Terminology

The current consumer hierarchy is:

```text
System
  └── Release
        └── Package
              └── File
```

- A **release** is currently a source-faithful title/variant: system, title,
  region, language, version, revision, dump state and other source claims have
  not been reconciled into a canonical game identity.
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

## Next architectural step

Add the missing **Title** layer without pretending it is an authoritative game
identity:

```text
System
  └── Title (exact-title browse/search cluster)
        └── Release
              └── Package
                    └── File
```

The first pass should group by exact `(system, display_title)` and link releases
to that cluster. Treat it as a browsing and metadata-search bucket, not proof
that every release describes the same software. On the current TOSEC data this
would reduce 841,867 releases to 308,581 exact-title clusters; 110,398 clusters
contain multiple releases and the largest contains 486.

Same-name collisions remain possible—for example, independently published games
called `Tetris`. The model must allow a cluster to be split later using reviewed
overrides or authoritative external identifiers.

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
