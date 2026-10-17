# SQL layers

SQL begins after [`derive.yml`](../derive.yml) has produced a usable relational
`derived` contract. [`pipeline.yml`](../pipeline.yml) is the executable index:

| Directory | Responsibility |
| --- | --- |
| [`layers/catalog`](layers/catalog/) | Project systems, exact-title clusters, releases and package membership |
| [`layers/facts`](layers/facts/) | Copy typed derived assertions into normalized facts with evidence |
| [`layers/identity`](layers/identity/) | Match complete exact-content signatures and build title aliases |
| [`layers/software`](layers/software/) | Resolve platform software and retain release-assignment evidence |
| [`layers/metadata`](layers/metadata/) | Attribute Libretro metadata to software through unambiguous exact SHA-1 matches |
| [`layers/scoring`](layers/scoring/) | Preserve preferences and rank releases within software |
| [`queries/explorer`](queries/explorer/) | Read-only explorer queries |

No SQL layer parses filenames or classifier JSON, resolves source paths, or
reloads file inventory. Those are derivation responsibilities.

```sh
python -m gamedb rebuild --plan
python -m gamedb rebuild
python -m gamedb rebuild --layers scoring
python -m gamedb rebuild --from-layer facts
```

Each selected layer runs as its own transaction. Temporary relations are used
only where one expensive result feeds several inserts or validations; they
never cross a layer boundary.
