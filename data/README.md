# Data files

These folders distinguish maintained inputs from material used for exploration.
Database storage, ROMs and media under `data/` remain ignored by Git.

## Reference data

[`reference/canonical_systems.csv`](reference/canonical_systems.csv) is the manually
maintained canonical system list. The derivation reference layer loads it into
`ref.canonical_system`; generated identity values are intentionally rebuild-local.

[`reference/system_mappings.csv`](reference/system_mappings.csv) is the complete
reviewed mapping from each `(romset, source manufacturer, source system)` triple
to a canonical system. It includes exact and normalized matches, explicit aliases,
and the reviewed NEC policies. New source triples must be added to this file.

[`reference/source_formats.json`](reference/source_formats.json) is the single
collection registry. It selects each DAT-identity strategy and declares its name
grammar: metadata anchors, delimiters, record separators and prefix-tag shapes.
[`reference/tag_vocabulary.json`](reference/tag_vocabulary.json)
contains the maintained values used by parsing and classification. Structural
parsing code consumes these definitions without embedding collection layouts.

[`reference/tag_categories.csv`](reference/tag_categories.csv) documents the
classification output categories. The derivation reference layer loads it into
`ref.tag_category`.

[`reference/path_mappings.csv`](reference/path_mappings.csv) maps stable RomVault
tree prefixes to host filesystem roots. The deriver applies the longest matching
prefix to archive/package paths while preserving the original source path.

## Research material

| File | Origin and purpose |
| --- | --- |
| [`research/romvault_dat_paths.csv`](research/romvault_dat_paths.csv) | Former `romset.csv`; exported DAT paths split into components, used to explore collection layouts |
| [`research/tosec.xlsx`](research/tosec.xlsx) | Existing TOSEC workbook, retained as research material |

These research files are not rebuild inputs. Their contents were preserved during
the move; regenerating an export should not overwrite maintained reference files.

Replayable derivation and projection are declared by [`derive.yml`](../derive.yml)
and [`pipeline.yml`](../pipeline.yml).
