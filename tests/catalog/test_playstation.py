from hashlib import md5
import os
import unittest

from sqlalchemy import text

from gamedb.catalog.disc_catalog import ARCHIVES
from gamedb.catalog.playstation import add_pressings, match_releases
from gamedb.catalog.playstation_media import _catalogue_manuals, add_manuals
from gamedb.catalog.playstation_source import game_record
from gamedb.database import create_database_engine


def game(post_id, title, rows=""):
    return game_record({
        "id": post_id, "title": {"rendered": title},
        "content": {"rendered": f"<table>{rows}</table>"},
    }, [title], {})


def archive(title, region="US"):
    key = md5(f"{title}/{region}".encode()).hexdigest()
    location = {"US": "USA", "JP": "Japan"}[region]
    return {"title": title, "archiveNames": [f"{title} ({location}).zip"], "signature": key,
            "softwareKey": key, "regions": [region], "channel": "optical-disc"}


class PlaystationRetailTests(unittest.TestCase):
    def test_printed_serials_and_historical_rating(self):
        release, = game(1, "Example &amp; Friends", """
            <tr><td>Released: July 1, 1999</td><td>CDs: 2</td></tr>
            <tr><td>Sony ID: SLUS-01142, 01163, PSRM: 018740, 018940</td></tr>
            <tr><td>ESRB: Kids to Adult – Mild Violence</td></tr>
            <tr><td>Players: 1 to 2 Players</td><td>Memory: 2 Blocks</td><td>Accessories: Analog, Vibration</td></tr>
        """)["releases"]
        self.assertEqual(release["titles"][0], "Example & Friends")
        self.assertEqual(release["date"], "July 1, 1999")
        self.assertEqual(release["productCodes"], ["SLUS-01142", "SLUS-01163"])
        self.assertEqual(release["packagedDiscs"], 2)
        self.assertEqual(release["rating"], "Kids to Adults")
        self.assertEqual(release["players"], "1 to 2 Players")
        self.assertEqual(release["memoryCard"], "2 Blocks")
        self.assertEqual(release["accessories"], "Analog, Vibration")

    def test_compilation_requires_all_verified_us_components(self):
        release_title = "Strider 2"
        archived = [archive(release_title), archive("Strider", "JP")]
        reviews = {"1": {"verifiedTitles": [release_title, "Strider"]}}
        for parts, expected in [(archived, "unmatched"), ([*archived, archive("Strider")], "matched")]:
            with self.subTest(expected=expected):
                entry = game(1, release_title)
                catalog = {"games": [entry]}
                match_releases(catalog, parts, reviews)
                release, = entry["releases"]
                self.assertEqual(release["status"], expected)
                if expected == "matched":
                    self.assertEqual({a["title"] for a in release["archives"]}, {release_title, "Strider"})
                    self.assertTrue(all(a["regions"] == ["US"] for a in release["archives"]))
                else:
                    self.assertNotIn("archives", release)
                    self.assertIn("Strider", release["reviewNote"]["text"])

    def test_bundle_can_reuse_verified_discs_and_original_manuals(self):
        originals = [archive("Game"), archive("Expansion")]
        games = [game(1, "Game"), game(2, "Expansion"), game(3, "Retail Double Pack")]
        catalog = {"games": games}
        reviews = {"3": {
            "bundleDiscs": [a["archiveNames"][0] for a in originals], "evidence": "Original retail case",
            "manuals": ["Game (USA).pdf", "Expansion (FE) (USA).pdf"],
        }}
        manuals = list(_catalogue_manuals("""
            <a href="https://www.videogamemanual.com/ps1/Game%20(USA).pdf">Original</a>
            <a href="https://www.videogamemanual.com/ps1/Expansion%20(FE)%20(USA).pdf">Original</a>
            <a href="https://www.videogamemanual.com/ps1/Expansion%20(Europe).pdf">PAL booklet</a>
        """))
        match_releases(catalog, originals, reviews)
        add_manuals(catalog, manuals, reviews)
        self.assertEqual(catalog["summary"]["matched"], 3)
        self.assertEqual(len(manuals), 2)
        releases = [entry["releases"][0] for entry in games]
        for release, title in zip(releases, ("Game", "Expansion")):
            self.assertEqual([m["name"] for m in release["manuals"]], [title])
        bundle = releases[2]
        self.assertEqual([a["signature"] for a in bundle["archives"]], [a["signature"] for a in originals])
        self.assertEqual([m["name"] for m in bundle["manuals"]], ["Game", "Expansion"])

    def test_retail_pressing_keeps_its_own_serial_and_manual(self):
        entry = game(1, "Game", "<tr><td>Sony ID: SLUS-00001</td></tr>")
        release, = entry["releases"]
        catalog = {"games": [entry]}
        archives = [archive("Game"), archive("Game - Dual Shock"), archive("Game - Dual Shock", "JP")]
        reviews = {"1": {"pressings": {"Game - Dual Shock": {
            "label": "Dual Shock Edition", "serials": ["SLUS-00002"], "manual": "Game - Dual Shock (USA).pdf",
        }}}}
        manuals = list(_catalogue_manuals("""
            <a href="https://www.videogamemanual.com/ps1/Game%20(USA).pdf">Original</a>
            <a href="https://www.videogamemanual.com/ps1/Game%20-%20Dual%20Shock%20(USA).pdf">Dual Shock</a>
        """))
        match_releases(catalog, archives, reviews)
        add_pressings(catalog, archives, reviews)
        add_manuals(catalog, manuals, reviews)
        self.assertEqual([a["signature"] for a in release["archives"]], [a["signature"] for a in archives[:2]])
        self.assertEqual(release["archives"][1]["pressing"], "Dual Shock Edition")
        self.assertEqual(release["productCodes"], ["SLUS-00001", "SLUS-00002"])
        self.assertEqual([m["name"] for m in release["manuals"]], ["Game", "Dual Shock Edition"])


@unittest.skipUnless(os.environ.get("GAMEDB_TEST_POSTGRES") == "1", "requires PostgreSQL")
class PlaystationArchiveTests(unittest.TestCase):
    def test_disc_groups_require_verified_retail_members(self):
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        sql = text(ARCHIVES.text.replace("catalog.", "pg_temp."))
        with engine.begin() as connection:
            connection.exec_driver_sql("""
                CREATE TEMP TABLE system (id int, manufacturer_name text, system_name text) ON COMMIT DROP;
                CREATE TEMP TABLE software (id int, system_id int, preferred_title_id int, identity_basis text,
                    source_snapshot_key text, source_software_id int, source_group_key text) ON COMMIT DROP;
                CREATE TEMP TABLE title (id int, cluster_key text) ON COMMIT DROP;
                CREATE TEMP TABLE software_release (software_id int, release_id int) ON COMMIT DROP;
                CREATE TEMP TABLE release (id int, display_title text, expected_media_parts int,
                    grouping_status text) ON COMMIT DROP;
                CREATE TEMP TABLE release_content_signature (release_id int, sha1_set_digest text) ON COMMIT DROP;
                CREATE TEMP TABLE release_package (release_id int, package_id int, media_sequence int,
                    media_description text, media_label text) ON COMMIT DROP;
                CREATE TEMP TABLE package (id int, archive_name text, source_collection text, resolved_path text) ON COMMIT DROP;
                CREATE TEMP TABLE package_file (package_id int, sha1_verified bool, sha1_hex text) ON COMMIT DROP;
                CREATE TEMP TABLE release_fact (release_id int, fact_key text, fact_value text) ON COMMIT DROP;

                INSERT INTO system VALUES (1, 'Sony', 'PlayStation');
                INSERT INTO title VALUES (1, 'game');
                INSERT INTO software VALUES (1, 1, 1, 'title_fallback', NULL, NULL, NULL);
                INSERT INTO release VALUES (1, 'Game', 2, 'media_complete'), (2, 'Missing Disc', 2, 'media_grouped'),
                    (3, 'Import', NULL, 'standalone'), (4, 'Demo', NULL, 'standalone'), (5, 'Unscanned', NULL, 'standalone'),
                    (6, 'Unverified', NULL, 'standalone'), (7, 'Ambiguous', NULL, 'media_ambiguous');
                INSERT INTO software_release SELECT 1, id FROM release;
                INSERT INTO release_content_signature SELECT id, md5(id::text) FROM release;
                INSERT INTO package SELECT id, id || '.zip', 'Redump', '/archive.zip' FROM generate_series(1, 8) id;
                INSERT INTO release_package VALUES (1, 2, 2, 'Final disc', NULL), (1, 1, 1, NULL, NULL),
                    (2, 3, 1, NULL, NULL), (3, 4, NULL, NULL, NULL), (4, 5, NULL, NULL, NULL),
                    (5, 6, NULL, NULL, NULL), (6, 7, NULL, NULL, NULL), (7, 8, 1, NULL, NULL);
                INSERT INTO package_file SELECT id, id <> 7, repeat('a', 40) FROM package WHERE id <> 6;
                INSERT INTO release_fact SELECT id, 'region', CASE WHEN id = 3 THEN 'JP' ELSE 'US' END FROM release;
                INSERT INTO release_fact VALUES (4, 'demo', 'standalone');
            """)
            result = connection.execute(sql, {
                "manufacturer": "Sony", "system": "PlayStation", "regions": ["US"],
            }).mappings().all()
        release, = result
        self.assertEqual(release["archiveNames"], ["1.zip", "2.zip"])
        self.assertEqual(release["discs"], [
            {"number": 1, "name": "1.zip"}, {"number": 2, "name": "2.zip", "label": "Final disc"},
        ])
