# Maintained reference inputs

These version-controlled files are the reviewed inputs to derivation:

- `canonical_systems.csv` defines the canonical system list.
- `system_mappings.csv` maps source system triples to canonical systems.
- `path_mappings.csv` maps RomVault prefixes to host filesystem roots.
- `libretro_thumbnail_systems.csv` maps canonical systems to reviewed
  libretro-thumbnails directories. It is intentionally sparse: an absent
  canonical system has no credible dedicated directory. `shared` rows reuse a
  combined Libretro directory; `broad` rows are reviewed namespace-level
  approximations rather than equivalent hardware names.
- `source_formats.json` declares collection identity and filename grammars.
- `tag_vocabulary.json` supplies maintained parsing/classification values.
- `tag_categories.csv` documents classification output categories.
- `software_overrides.csv` records stable source-release assignments or
  exclusions. `assign` rows sharing a system and `target_key` merge into one
  manually maintained software identity; `exclude` rows leave target fields
  empty and block automatic inheritance. Selectors use source collection,
  archive name and one-based record index rather than rebuild-local IDs.
- `software_corrections.csv` contains promoted release-to-software decisions.
  It relates complete release-content signatures within a canonical system;
  `assign` follows a target signature while `separate` creates an independent
  manual identity. Working web corrections remain in `app` until promoted.

The deriver or catalog builder loads these into `ref` or reads them directly.
live outside `data/` so Docker can exclude all runtime data—including the
permission-protected PostgreSQL directory—from its build context.
