# GameDB (new)

RDB-first local metadata library.

## Layout
- app/core/rdb: RDB reader + importer
- app/db: storage layer
- app/services: query helpers
- app/cli: command-line entrypoints
- app/web: Django project (later)
- data: mounted inputs (rdb, dat, etc.)

## Docker
This repo includes a minimal Postgres service.

```
docker compose up -d
```

## Database
Initialize the schema:

```
python -c "from app.db.session import init_db; init_db()"
```

## CLI
Run with:

```
python -m app.cli.main init-db
python -m app.cli.main import-rdb path/to/file_or_dir
```

Log skipped rows:

```
python -m app.cli.main import-rdb /data/rdb --skipped-log /tmp/skipped_rows.log
```

## Docker CLI
Run commands inside the app container:

```
docker compose run --rm app python -m app.cli.main init-db
docker compose run --rm app python -m app.cli.main import-rdb /data/rdb
```

## Web
Start the browse API:

```
docker compose up -d web
```

Then visit `http://localhost:8000/` for a JSON list of systems.

## Secrets (SOPS)
Encrypt `.env` into `.sops.env`:

```
sops --encrypt --output .sops.env .env
```

Decrypt for local use:

```
sops --decrypt --output .env .sops.env
```
