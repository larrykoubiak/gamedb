# V1 Snapshot

The legacy application model in `app/db/models.py` defined:

- `systems`
- `titles`
- `releases`
- `roms`
- `attributes`
- `media`

Those public tables have been removed. The importer and browser code is retained
for reference; the current RomVault model is documented in `docs/database.md`.
