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
row to `system_mappings.csv`, and rebuild from the reference layer. That layer
discards its disposable downstream projections before recreating its output.

```sh
python -m gamedb rebuild --from-layer reference
```

The deriver loads both files into `ref`; its system layer applies the mappings
when creating `derived.dat`.
The source mapping key includes `romset`, allowing identical labels from different
collections to diverge later if necessary.
