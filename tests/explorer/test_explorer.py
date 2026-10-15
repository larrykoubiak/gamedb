import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gamedb.explorer.server import (
    ASSET_DIRECTORY,
    _database_error,
    _load_project_environment,
    _resolve_explorer_port,
)
from gamedb.explorer.repository import (
    QUERY_DIRECTORY,
    CatalogRepository,
    quote_sql_text,
)


class ExplorerTests(unittest.TestCase):
    def test_sql_text_escapes_quotes(self):
        self.assertEqual(quote_sql_text("Bob's"), "'Bob''s'")

    def test_title_query_uses_bounded_numeric_paging_and_filter(self):
        query = CatalogRepository("default").titles_sql(
            269, 100, 200, "Final Fantasy III"
        )
        self.assertIn("title.system_id = 269", query)
        self.assertIn("LIMIT 100 OFFSET 200", query)
        self.assertIn("lower('Final Fantasy III')", query)
        self.assertIn("catalog.title_alias", query)

    def test_static_assets_are_packaged_with_the_module(self):
        for name in ("index.html", "styles.css", "app.js"):
            self.assertTrue((ASSET_DIRECTORY / name).is_file())

    def test_explorer_sql_is_kept_in_reviewable_query_files(self):
        for name in ("systems.sql", "titles.sql", "title_releases.sql"):
            self.assertTrue((QUERY_DIRECTORY / name).is_file())

    def test_repository_rejects_non_numeric_query_bindings(self):
        repository = CatalogRepository("default")
        with self.assertRaisesRegex(ValueError, "system_id must be an integer"):
            repository.titles_sql("269", 100, 0)  # type: ignore[arg-type]

    def test_system_query_targets_preferred_release_view(self):
        query = CatalogRepository("default").systems_sql()
        self.assertIn("catalog.user_preferred_release", query)
        self.assertIn("user_account.username = 'default'", query)

    def test_release_details_include_scores_packages_and_hashes(self):
        query = CatalogRepository("default").title_releases_sql(267707)
        self.assertIn("score.title_id = 267707", query)
        self.assertIn("catalog.package_content_signature", query)
        self.assertIn("'sha1', file.sha1_hex", query)
        self.assertIn("score.rank_within_title", query)

    def test_project_env_supplies_missing_postgres_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# local settings\nPGHOST=db.example\nPGPORT='9876'\n"
                "GAMEDB_EXPLORER_PORT=8765\nIGNORED=value\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"PGHOST": "explicit.example"}, clear=True):
                loaded = _load_project_environment(path)
                self.assertEqual(loaded, ("PGPORT", "GAMEDB_EXPLORER_PORT"))
                self.assertEqual(os.environ["PGHOST"], "explicit.example")
                self.assertEqual(os.environ["PGPORT"], "9876")
                self.assertEqual(os.environ["GAMEDB_EXPLORER_PORT"], "8765")
                self.assertNotIn("IGNORED", os.environ)

    def test_explorer_port_uses_environment_unless_cli_overrides_it(self):
        with patch.dict(os.environ, {"GAMEDB_EXPLORER_PORT": "8765"}, clear=True):
            self.assertEqual(_resolve_explorer_port(None), 8765)
            self.assertEqual(_resolve_explorer_port(9000), 9000)

    def test_explorer_port_rejects_invalid_environment_value(self):
        with patch.dict(os.environ, {"GAMEDB_EXPLORER_PORT": "not-a-port"}, clear=True):
            with self.assertRaisesRegex(SystemExit, "must be an integer"):
                _resolve_explorer_port(None)

    def test_database_connection_error_is_actionable(self):
        message = _database_error(
            'psql: error: connection to server on socket "/tmp/.s.PGSQL.5432" failed'
        )
        self.assertIn("project .env", message)


if __name__ == "__main__":
    unittest.main()
