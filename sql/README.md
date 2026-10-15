# SQL layers

[`pipeline.yml`](../pipeline.yml) is the executable index for this directory.
It names every layer, explains its responsibility, and references its SQL in
execution order. SQL files do not decide which other layers should run; the
workflow selection does.

| Directory | Responsibility |
| --- | --- |
| [`layers/reset`](layers/reset/) | Remove disposable schemas for a clean replay from staging |
| [`layers/reference`](layers/reference/) | Load maintained mappings and discover DATs from staging |
| [`layers/archive_names`](layers/archive_names/) | Persist Python parsing and classification output |
| [`layers/catalog`](layers/catalog/) | Build core systems, titles, releases, packages, and files |
| [`layers/facts`](layers/facts/) | Normalize release facts and retain source evidence |
| [`layers/identity`](layers/identity/) | Build exact-content signatures, matches, and title aliases |
| [`layers/scoring`](layers/scoring/) | Maintain preferences and compile disposable scores |

Read-only consumer SQL is separate from the rebuild:

| Directory | Responsibility |
| --- | --- |
| [`queries/explorer`](queries/explorer/) | Systems, preferred-title pages, and ranked-release details used by `CatalogRepository` |

Run the complete story or inspect it without executing anything:

```sh
python -m gamedb rebuild --plan
python -m gamedb rebuild
```

During development, rebuild only the affected layer or the affected layer and
everything after it:

```sh
python -m gamedb rebuild --layers scoring
python -m gamedb rebuild --from-layer catalog
```

Every generated database object remains reproducible from `staging.rv_files`
and version-controlled rules/reference data. Selecting layers is a development
convenience, not a dependency on preserved generated state.
