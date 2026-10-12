# System mapping

System reconciliation is explicit reference data rather than runtime inference.

[`canonical_systems.csv`](../data/reference/canonical_systems.csv) defines the 453
canonical systems. [`system_mappings.csv`](../data/reference/system_mappings.csv)
maps every distinct `(romset, source_manufacturer, source_system)` triple found in
the retained RomVault import to one of those systems.

The mapping file contains exact matches, normalized matches, reviewed aliases and
the three manual NEC policies. These method labels are provenance only; rebuilding
does not repeat fuzzy matching.

When staging introduces a new source triple, the rebuild stops. Review it, add one
row to `system_mappings.csv`, and run the complete rebuild. The foundation script
deliberately refuses to hide dependent derived/catalog objects behind `CASCADE`.

```sh
set -a
. ./.env
set +a
psql -X -v ON_ERROR_STOP=1 -f sql/rebuild/000_reset.sql
psql -X -v ON_ERROR_STOP=1 -f sql/rebuild/001_reference_and_dat.sql
python scripts/rebuild_archive_names.py
psql -X -v ON_ERROR_STOP=1 -f sql/rebuild/003_catalog.sql
```

The script loads both files into `ref` and joins them while creating `derived.dat`.
The source mapping key includes `romset`, allowing identical labels from different
collections to diverge later if necessary.
