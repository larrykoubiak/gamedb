# Maintained reference inputs

These version-controlled files are the reviewed inputs to derivation:

- `canonical_systems.csv` defines the canonical system list.
- `system_mappings.csv` maps source system triples to canonical systems.
- `path_mappings.csv` maps RomVault prefixes to host filesystem roots.
- `source_formats.json` declares collection identity and filename grammars.
- `tag_vocabulary.json` supplies maintained parsing/classification values.
- `tag_categories.csv` documents classification output categories.

The deriver loads these into `ref` or reads them as parser configuration. They
live outside `data/` so Docker can exclude all runtime data—including the
permission-protected PostgreSQL directory—from its build context.
