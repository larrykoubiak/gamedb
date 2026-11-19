# Maintained reference inputs

These version-controlled files are the reviewed inputs to derivation:

- `canonical_systems.csv` defines the canonical system list and each system's
  required category (`console`, `handheld`, `computer`, `arcade`, or `other`).
  See [classification policies](../docs/system_mapping.md).
- `system_mappings.csv` maps source system triples to canonical systems.
- `path_mappings.csv` maps RomVault prefixes to host filesystem roots.
- `libretro_thumbnail_systems.csv` maps canonical systems to reviewed
  libretro-thumbnails directories. It is intentionally sparse: an absent
  canonical system has no credible dedicated directory. `shared` rows reuse a
  combined Libretro directory; `broad` rows are reviewed namespace-level
  approximations rather than equivalent hardware names.
- `launchbox_platforms.csv` explicitly maps canonical systems to LaunchBox
  platform names for the candidate coverage report. Missing systems are left
  unmapped; hardware families and unrelated PC operating systems are not
  guessed from names at report time.
- `launchbox_artwork.csv` links reviewed release content to a LaunchBox game
  for artwork lookup. The platform, game ID and title identify the source
  record. The media builder uses these links for empty artwork slots. For
  `r2_` images, `verified_file_name` and `verified_crc32` record a download
  whose bytes matched the checksum in the imported image record.
- `system_icons.csv` maps canonical systems to bundled RetroArch platform icons.
  `python scripts/sync_system_icons.py` refreshes pinned assets and the runtime
  manifest; unmatched systems keep a neutral icon and their text label.
- `genre_aliases.csv` maps equivalent RDB and LaunchBox genre spellings to
  canonical names during the metadata rebuild. Unlisted names are preserved;
  subgenres are not automatically merged into their parent genres.
- `source_formats.json` declares collection identity and filename grammars.
- `tag_vocabulary.json` supplies maintained parsing/classification values.
- `tag_categories.csv` documents classification output categories.
- `software_overrides.csv` records stable source-release assignments or
  exclusions. `assign` rows sharing a system and `target_key` merge into one
  manually maintained software identity; `exclude` rows leave target fields
  empty and block automatic inheritance. Selectors use source collection,
  archive name and one-based record index rather than rebuild-local IDs.
- `software_corrections.csv` records reviewed release-to-software decisions.
  It relates complete release-content signatures within a canonical system.
  Each `assign` points directly to content in the destination game. A
  `separate` row creates an independent identity. Working web corrections
  remain in `app` until promoted.
- `exo_work_matches.csv` joins verified eXo game identities across collections and
  edition menus. Each row maps an earlier work key directly to the chosen game and
  records the supporting evidence. Edition keys still identify each playable choice.

The title reconciliation notes give both catalog names and the evidence for
each move. Some English Translations archives retain the original title in a
ROM member. TOSEC archives can name an alternate title in an `[aka]` tag.
Spelling corrections include the credited publisher and year where available.
Regional titles can also be checked against the LaunchBox game ID in the
note (metadata ZIP SHA-256
`d195ae79bf456b6d97fd8ab76a80147f53015e10a7a22253b23ce0781fd53d04`).
Cartridge codes and parent/clone references come from the
[Libretro RDB snapshot](https://github.com/libretro/libretro-database/tree/12c21cf79f1e20eff6ac68b80875816c717d0a7a/rdb)
and [MAME 0.285 software lists](https://github.com/mamedev/mame/tree/mame0285/hash).
Publisher confirmations include Nintendo's account of the European
[Star Fox 64 title](https://www.nintendo.com/en-gb/News/2016/April/Why-Star-Fox-64-fans-will-love-Star-Fox-Zero-1097923.html)
and Sega's announcement of the three regional names for
[Project Rub](https://www.nintendoworldreport.com/news/10193/goodbye-feel-the-magic-xyxx).

The deriver or catalog builder loads these files into `ref` or reads them
directly. Keeping them outside `data/` lets Docker exclude runtime data,
including the permission-protected PostgreSQL directory, from its build context.
