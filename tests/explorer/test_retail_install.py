import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from gamedb.catalog.software_identity import SOFTWARE_KEY_SQL
from gamedb.database import create_database_engine
from gamedb.explorer.repository import CatalogRepository, quote_sql_text
from gamedb.explorer.server import ExplorerHandler


class RetailInstallLinksTests(unittest.TestCase):
    def test_detail_links_require_matched_archives_with_available_packages(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "japan.zip"
            package.touch()
            japan = {"signature": "a" * 32, "softwareKey": "d" * 32}
            missing = {"signature": "b" * 32}
            ambiguous = {"signature": "c" * 32}
            game = {"releases": [
                {"status": "matched", "archives": [japan, missing]},
                {"status": "ambiguous", "archives": [ambiguous]},
            ]}
            repository = Mock()
            repository.retail_install_paths.return_value = [
                {"linkNo": 1, "paths": [str(package)]},
                {"linkNo": 2, "paths": [str(root / "missing.zip")]},
            ]
            handler = SimpleNamespace(server=SimpleNamespace(rom_root=root, repository=repository))
            ExplorerHandler._add_retail_install_urls(handler, game)
            self.assertEqual(japan["installManifestUrl"],
                             f"/api/v1/releases/{'a' * 32}/install-manifest?software_key={'d' * 32}")
            self.assertNotIn("installManifestUrl", missing)
            self.assertNotIn("installManifestUrl", ambiguous)
            repository.retail_install_paths.assert_called_once_with([japan, missing])


@unittest.skipUnless(os.environ.get("GAMEDB_TEST_POSTGRES") == "1", "requires PostgreSQL")
class RetailInstallLookupTests(unittest.TestCase):
    def test_install_lookup_uses_published_packages_and_preserves_legacy_eligibility(self):
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        with engine.connect() as connection:
            connection.exec_driver_sql("""
                CREATE TEMP TABLE release AS SELECT generate_series(1, 4) AS id;
                CREATE TEMP TABLE system AS SELECT 1 AS id, 'Maker' AS manufacturer_name, 'Console' AS system_name;
                CREATE TEMP TABLE title AS SELECT 1 AS id, 'game' AS cluster_key;
                CREATE TEMP TABLE software AS SELECT 1 AS id, 1 AS system_id, 1 AS preferred_title_id,
                    'Game' AS display_name, 'test' AS identity_basis, NULL::text AS source_snapshot_key,
                    NULL::bigint AS source_software_id, NULL::text AS source_group_key;
                CREATE TEMP TABLE software_release AS SELECT id AS release_id, 1 AS software_id FROM release;
                CREATE TEMP TABLE app_user AS SELECT 1 AS id, 'test' AS username;
                CREATE TEMP TABLE user_preferred_release AS SELECT 1 AS user_id, 1 AS software_id, 1 AS release_id;
                CREATE TEMP TABLE user_rom_hack_fallback (user_id int, software_id int, release_id int);
                CREATE TEMP TABLE package AS SELECT fixture.*, '/roms/' || archive_name AS resolved_path,
                    'Fixture' AS source_collection
                FROM (VALUES
                    (11, 1, 'USA.zip', NULL::int, 'a'),
                    (21, 2, 'Mirror 1.zip', 1, 'b'), (22, 2, 'Mirror 2.zip', 2, 'c'),
                    (31, 3, 'Japan Z.zip', 1, 'b'), (32, 3, 'Japan A.zip', 2, 'c'),
                    (41, 4, 'Beta.zip', NULL, 'd')
                ) fixture(id, release_id, archive_name, disc, hash_digit);
                CREATE TEMP TABLE release_package AS SELECT release_id, id AS package_id,
                    disc AS media_sequence, disc AS media_part, 2 AS media_total,
                    'disc' AS media_type, NULL::text AS media_side FROM package;
                CREATE TEMP TABLE package_file AS SELECT id, id AS package_id,
                    archive_name || '.bin' AS member_path, archive_name || '.bin' AS file_name,
                    128 AS size, repeat(hash_digit, 40) AS sha1_hex, TRUE AS sha1_verified FROM package;
                CREATE TEMP TABLE package_content_signature AS SELECT id AS package_id, release_id,
                    1 AS rom_count, md5(repeat(hash_digit, 40)) AS sha1_set_digest FROM package;
                CREATE TEMP TABLE release_content_signature AS SELECT release_id, count(*) AS package_count,
                    md5(string_agg(sha1_set_digest, E'\n' ORDER BY sha1_set_digest)) AS sha1_set_digest
                    FROM package_content_signature GROUP BY release_id;
            """)

            def query(sql):
                return connection.exec_driver_sql(
                    sql.replace("catalog.", "pg_temp.").replace("app.", "pg_temp."),
                    execution_options={"no_parameters": True},
                ).scalar_one()

            repository = CatalogRepository("test", Mock(query=Mock(side_effect=query)))
            signatures = query("SELECT jsonb_object_agg(release_id, sha1_set_digest) FROM pg_temp.release_content_signature")
            usa, japan, beta = [signatures[key] for key in ("1", "3", "4")]
            self.assertEqual(repository.install_manifest(usa)["packages"][0]["archiveName"], "USA.zip")
            self.assertIsNone(repository.install_manifest(japan))
            software_key = query(f"""
                SELECT {SOFTWARE_KEY_SQL}
                FROM pg_temp.software software CROSS JOIN pg_temp.system system CROSS JOIN pg_temp.title title
            """)
            archive = {"softwareId": 999, "softwareKey": software_key, "signature": japan,
                       "archiveNames": ["Japan Z.zip", "Japan A.zip"]}

            connection.exec_driver_sql("CREATE TEMP TABLE snes_retail_catalog (singleton boolean, payload jsonb)")

            def publish(item):
                payload = {"games": [{"releases": [
                    {"status": "matched", "archives": [item]},
                    {"status": "ambiguous", "archives": [dict(archive, signature=beta, archiveNames=["Beta.zip"])]},
                ]}]}
                connection.exec_driver_sql("DELETE FROM pg_temp.snes_retail_catalog")
                connection.exec_driver_sql(
                    f"INSERT INTO pg_temp.snes_retail_catalog VALUES (true, {quote_sql_text(json.dumps(payload))})"
                )

            publish(archive)
            manifest = repository.install_manifest(japan)
            self.assertEqual(manifest["releaseSignature"], japan)
            self.assertEqual([(p["archiveName"], p["mediaSequence"]) for p in manifest["packages"]],
                             [("Japan Z.zip", 1), ("Japan A.zip", 2)])
            self.assertEqual(manifest["packages"][0]["files"][0]["sha1"], "b" * 40)
            connection.exec_driver_sql("INSERT INTO pg_temp.user_preferred_release VALUES (1, 1, 2)")
            self.assertEqual(repository.install_manifest(japan)["packages"][0]["archiveName"], "Mirror 1.zip")
            scoped = repository.install_manifest(japan, software_key=software_key)
            self.assertEqual(scoped["packages"][0]["archiveName"], "Japan Z.zip")
            self.assertIsNone(repository.install_manifest(japan, software_key="f" * 32))
            connection.exec_driver_sql("DELETE FROM pg_temp.user_preferred_release WHERE release_id = 2")
            self.assertEqual(repository.retail_install_paths([archive]), [{
                "linkNo": 1, "paths": ["/roms/Japan Z.zip", "/roms/Japan A.zip"],
            }])
            self.assertIsNone(repository.install_manifest(beta))
            connection.exec_driver_sql("INSERT INTO pg_temp.user_rom_hack_fallback VALUES (1, 1, 4)")
            self.assertEqual(repository.install_manifest(beta)["packages"][0]["archiveName"], "Beta.zip")

            for invalid in (dict(archive, softwareKey="stale"), dict(archive, archiveNames=["Japan Z.zip"])):
                publish(invalid)
                self.assertIsNone(repository.install_manifest(japan))
                self.assertEqual(repository.retail_install_paths([invalid]), [])
            publish(archive)
            connection.exec_driver_sql("UPDATE pg_temp.package_file SET sha1_hex = repeat('0', 40) WHERE id = 31")
            self.assertIsNone(repository.install_manifest(japan))
            self.assertEqual(repository.retail_install_paths([archive]), [])
