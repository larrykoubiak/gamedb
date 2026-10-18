import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gamedb.explorer.server import (
    ASSET_DIRECTORY,
    _corrections_enabled,
    _database_error,
    _load_project_environment,
    _resolve_explorer_port,
    _resolve_media_path,
    _resolve_rom_path,
    _byte_range,
    _api_authorized,
    _api_key,
    _request_client,
)
from gamedb.explorer.repository import (
    QUERY_DIRECTORY,
    CatalogRepository,
    quote_sql_text,
)


class ExplorerTests(unittest.TestCase):
    def test_versioned_api_requires_an_exact_bearer_key(self):
        key = "a" * 43

        self.assertTrue(_api_authorized(f"Bearer {key}", key))
        self.assertTrue(_api_authorized(f"bearer {key}", key))
        self.assertFalse(_api_authorized(None, key))
        self.assertFalse(_api_authorized(f"Bearer {key}x", key))
        self.assertFalse(_api_authorized(f"Basic {key}", key))

    def test_api_key_configuration_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "at least 32"):
                _api_key()
        with patch.dict(os.environ, {"GAMEDB_API_KEY": "b" * 43}, clear=True):
            self.assertEqual(_api_key(), "b" * 43)

    def test_access_log_accepts_only_a_valid_forwarded_ip(self):
        self.assertEqual(_request_client("203.0.113.8", "172.20.0.1"), "203.0.113.8")
        self.assertEqual(_request_client("bad\nlog", "172.20.0.1"), "172.20.0.1")

    def test_sql_text_escapes_quotes(self):
        self.assertEqual(quote_sql_text("Bob's"), "'Bob''s'")

    def test_title_query_uses_bounded_numeric_paging_and_filter(self):
        query = CatalogRepository("default").titles_sql(
            269, 100, 200, "Final Fantasy III"
        )
        self.assertIn("software.system_id = 269", query)
        self.assertIn("LIMIT 100 OFFSET 200", query)
        self.assertIn("lower('Final Fantasy III')", query)
        self.assertIn("catalog.software_release", query)
        self.assertIn("catalog.software_media", query)
        self.assertIn("'media', items.media", query)

    def test_media_paths_stay_below_the_thumbnail_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "Nintendo%" / "Named_Boxarts" / "A Game.png"

            self.assertEqual(
                _resolve_media_path(
                    root, "Nintendo%25/Named_Boxarts/A%20Game.png"
                ),
                expected,
            )
            with self.assertRaisesRegex(ValueError, "Invalid media path"):
                _resolve_media_path(root, "../outside.png")

    def test_explorer_renders_catalog_artwork(self):
        script = (ASSET_DIRECTORY / "app.js").read_text(encoding="utf-8")

        self.assertIn('["boxart", "title", "snap", "logo"]', script)
        self.assertIn("/media/", script)

    def test_static_assets_are_packaged_with_the_module(self):
        for name in ("index.html", "styles.css", "app.js"):
            self.assertTrue((ASSET_DIRECTORY / name).is_file())

    def test_explorer_exposes_correction_without_review_queue(self):
        index = (ASSET_DIRECTORY / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIRECTORY / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('value="confirm"', index)
        self.assertIn('/app.js?v=', index)
        self.assertIn('button.textContent = "Correct…"', script)
        self.assertNotIn("identityNeedsReview", script)
        self.assertIn("JSON.parse(body)", script)

    def test_explorer_sql_is_kept_in_reviewable_query_files(self):
        for name in (
            "systems.sql", "titles.sql", "title_releases.sql",
            "software_facts.sql",
            "system_software_facts.sql",
            "install_manifest.sql",
            "catalog_revision.sql",
            "correction_targets.sql", "create_correction.sql",
            "disable_correction.sql",
        ):
            self.assertTrue((QUERY_DIRECTORY / name).is_file())

    def test_repository_rejects_non_numeric_query_bindings(self):
        repository = CatalogRepository("default")
        with self.assertRaisesRegex(ValueError, "system_id must be an integer"):
            repository.titles_sql("269", 100, 0)  # type: ignore[arg-type]

    def test_system_query_targets_preferred_release_view(self):
        query = CatalogRepository("default").systems_sql()
        self.assertIn("app.user_preferred_release", query)
        self.assertIn("user_account.username = 'default'", query)
        self.assertIn("'key', systems.system_key", query)

    def test_catalog_snapshot_uses_scoring_generation_and_stable_system_key(self):
        repository = CatalogRepository("default")

        revision = repository.catalog_revision_sql()
        titles = repository.titles_sql(269, 100, 0)

        self.assertIn("app.user_score_generation", revision)
        self.assertIn("catalog.software_fact", revision)
        self.assertIn("metadata.signature", revision)
        self.assertIn("'default'", revision)
        self.assertIn("preferredReleaseSignature", titles)
        self.assertIn("catalog.release_content_signature", titles)

    def test_release_details_include_scores_packages_and_hashes(self):
        query = CatalogRepository("default").software_releases_sql(267707)
        self.assertIn("score.software_id = 267707", query)
        self.assertIn("catalog.package_content_signature", query)
        self.assertIn("catalog.package_file", query)
        self.assertNotIn("derived.file", query)
        self.assertIn("'sha1', file.sha1_hex", query)
        self.assertIn("score.rank_within_software", query)
        self.assertIn("release_content_signature", query)

    def test_software_facts_include_conflicts_support_and_provenance(self):
        query = CatalogRepository("default").software_facts_sql(267707)

        self.assertIn("fact.software_id = 267707", query)
        self.assertIn("catalog.software_fact_evidence", query)
        self.assertIn("'candidateCount', value_count", query)
        self.assertIn("'matchedContentCount', matched_content_count", query)
        self.assertIn("'sourceDatabases', source_databases", query)

        script = (ASSET_DIRECTORY / "app.js").read_text(encoding="utf-8")
        self.assertIn("renderSoftwareFacts", script)
        self.assertIn("candidate ${candidate.rank}/${candidate.candidateCount}", script)
        self.assertIn("/facts`", script)

    def test_launcher_snapshot_receives_software_facts(self):
        query = CatalogRepository("default").system_software_facts_sql(269)

        self.assertIn("software.system_id = 269", query)
        self.assertIn("jsonb_object_agg(software_id::text", query)
        self.assertIn("'sourceDatabases', source_databases", query)

        class SnapshotRepository(CatalogRepository):
            def systems(self):
                return [{
                    "id": 269,
                    "key": "a" * 32,
                    "manufacturer": "Nintendo",
                    "name": "SNES",
                    "gameCount": 1,
                }]

            def titles(self, system_id, limit, offset, title_filter=""):
                return {"items": [{"softwareId": 42, "title": "Example"}]}

            def system_software_facts(self, system_id):
                return {"42": [{"key": "genre", "values": []}]}

        payload = SnapshotRepository("default").system_software("a" * 32, "rev")
        self.assertEqual(
            payload["items"][0]["softwareFacts"],
            [{"key": "genre", "values": []}],
        )

    def test_install_manifest_requires_preferred_release_and_hides_paths_at_transport(self):
        query = CatalogRepository("default").install_manifest_sql("a" * 32)
        self.assertIn("app.user_preferred_release", query)
        self.assertIn("catalog.package_file", query)
        self.assertIn("'resolvedPath', package.resolved_path", query)
        self.assertIn("'packageSignature'", query)

    def test_rom_paths_stay_below_configured_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "game.zip"
            package.write_bytes(b"zip")
            self.assertEqual(_resolve_rom_path(root, str(package)), package)
            with self.assertRaisesRegex(ValueError, "outside"):
                _resolve_rom_path(root, "/tmp/outside.zip")

    def test_single_byte_ranges_include_open_and_suffix_forms(self):
        self.assertEqual(_byte_range(None, 100), None)
        self.assertEqual(_byte_range("bytes=10-19", 100), (10, 19))
        self.assertEqual(_byte_range("bytes=90-", 100), (90, 99))
        self.assertEqual(_byte_range("bytes=-12", 100), (88, 99))
        with self.assertRaises(ValueError):
            _byte_range("bytes=100-", 100)

    def test_correction_target_search_is_system_scoped(self):
        query = CatalogRepository("default").correction_targets_sql(
            269, 5883, "Final Fantasy"
        )

        self.assertIn("software.system_id = 269", query)
        self.assertIn("software.id <> 5883", query)
        self.assertIn("lower('Final Fantasy')", query)

    def test_correction_requires_content_signatures(self):
        repository = CatalogRepository("default")

        with self.assertRaisesRegex(ValueError, "32-character"):
            repository.create_correction_sql(
                269, "not-a-signature", "separate", None, "test"
            )

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

    def test_corrections_require_explicit_local_enablement(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_corrections_enabled())
        with patch.dict(os.environ, {"GAMEDB_ENABLE_CORRECTIONS": "1"}, clear=True):
            self.assertTrue(_corrections_enabled())

    def test_database_connection_error_is_actionable(self):
        message = _database_error(
            'psql: error: connection to server on socket "/tmp/.s.PGSQL.5432" failed'
        )
        self.assertIn("project .env", message)


if __name__ == "__main__":
    unittest.main()
