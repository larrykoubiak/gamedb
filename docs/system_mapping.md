# System mapping

System reconciliation is explicit reference data rather than runtime inference.

[`canonical_systems.csv`](../reference/canonical_systems.csv) defines the 455
canonical systems. [`system_mappings.csv`](../reference/system_mappings.csv)
maps every distinct `(romset, source_manufacturer, source_system)` triple found in
the retained RomVault import to one of those systems.

The mapping file contains exact matches, normalized matches, reviewed aliases and
the three manual NEC policies. These method labels are provenance only; rebuilding
does not repeat fuzzy matching.

When staging introduces a new source triple, the rebuild stops. Review it, add one
row to `system_mappings.csv`, and rebuild from the reference layer. That layer
discards its disposable downstream projections before recreating its output.

```sh
python -m gamedb derive --from-layer reference
python -m gamedb rebuild
```

The deriver loads both files into `ref`; its system layer applies the mappings
when creating `derived.dat`.
The source mapping key includes `romset`, allowing identical labels from different
collections to diverge later if necessary.

Every canonical system has one required `category`: `console`, `handheld`,
`computer`, `arcade`, or `other`. These are reviewed platform classifications,
independent of cartridge, tape, disk, optical, or downloaded software formats.
The reference loader rejects missing or unknown categories before replacing data;
both the reference and catalog schemas enforce the vocabulary.

The explorer category selector narrows the manufacturer/system tree and combines
with its text filter. Its count shows matching systems out of all library systems.
It does not change the selected platform or the library-wide All platforms search.
The systems API exposes the same `category` field for launcher clients.

Policies for ambiguous systems:

- Console expansions follow their gaming platform: Famicom Disk System, 64DD,
  Mega-CD, PC-FXGA, and Satellaview are consoles. Family BASIC is a computer;
  the Family Computer Network System is a dedicated service device (`other`).
- Computer-derived gaming appliances such as Amiga CD32/CDTV, Pippin, and
  C64DTV are consoles. General-purpose computer families remain computers,
  including the combined Laser 2001 & CreatiVision entry.
- Virtual Boy and tabletop Adventure Vision are consoles; Game & Watch,
  PocketStation, and Visual Memory System are handhelds.
- The combined SNK Neo-Geo entry is assigned to arcade as a browsing policy;
  Neo Geo CD is a console. AES and MVS are distinct home and arcade variants
  ([MAME documentation](https://wiki.mamedev.org/index.php/Driver:NeoGeo));
  a future split into canonical variants could give each its own category.
- Calculators, instruments, dedicated word processors, virtual machines,
  media/service peripherals, and cross-platform compilations use `other`.
  Portable general-purpose computers remain computers.

Review the category when adding a system. Change the CSV and rebuild from the
reference layer to revise an assignment; the UI contains no system-name rules.
