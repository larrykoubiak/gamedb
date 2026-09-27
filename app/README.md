# Legacy application

The Libretro RDB importer, thumbnail importer, SQLAlchemy models and Django web
application in this directory belong to the previous data model. Their public
tables have been removed. Do not use `app.cli.main init-db` for the RomVault core.

Current code lives in `gamedb/`. The RomVault name-parser module and command here
are compatibility wrappers only; use `python -m gamedb` for active work.

The older code is retained for reference and possible reuse. The old web and
Cloudflare services in `compose.yaml` are opt-in under the `legacy` profile.
