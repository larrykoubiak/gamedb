import os
import unittest
from pathlib import Path
from uuid import uuid4

from gamedb.database import create_database_engine


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ScoringContractTests(unittest.TestCase):
    def test_bonus_disc_is_an_explicit_media_label_penalty(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("'media_label', 'equals', 'Bonus Disc', -500", preferences)
        self.assertNotIn("'media_label', 'present'", preferences)

    def test_undubs_are_explicitly_preferred(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("'dump_modification', 'equals', 'undub', 150", preferences)

    def test_default_policy_names_contextual_translation_roles(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("preferred_language_fallback", preferences)
        self.assertIn("'translation_role', 'equals', 'redundant'", preferences)
        self.assertIn("'translation_role', 'equals', 'nonpreferred'", preferences)

    def test_preferences_support_exact_system_overrides(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")
        generation = (
            PROJECT_ROOT / "sql/layers/scoring/020_generate_scores.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("system_manufacturer, system_name", preferences)
        self.assertIn("'Atari', 'ST'", preferences)
        self.assertIn(
            "preference.system_id IS NULL OR preference.system_id = title.system_id",
            generation,
        )

    def test_virtual_console_is_an_explicit_distribution_penalty(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("'virtual_console', -100", preferences)
        self.assertIn("'wii_u_virtual_console', -100", preferences)


@unittest.skipUnless(os.environ.get('GAMEDB_TEST_POSTGRES') == '1', 'requires PostgreSQL')
class PreferredReleaseCacheTests(unittest.TestCase):
    def test_rom_hack_filter_keeps_language_patches_and_ranks_only_eligible_releases(self):
        schema = 'test_hacks_' + uuid4().hex
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        with engine.connect() as c:
            c.exec_driver_sql(f'CREATE SCHEMA {schema}')
            c.exec_driver_sql(f"""
                CREATE TABLE {schema}.user_release_score (
                    user_id bigint, software_id bigint, release_id bigint, score bigint,
                    breakdown jsonb, rank_within_software bigint
                );
                CREATE TABLE {schema}.release_fact (release_id bigint, fact_key text, fact_value text);
                INSERT INTO {schema}.user_release_score VALUES
                    (1,1,10,90,'[]',1),(1,1,11,50,'["fix"]',2),(1,1,12,50,'[]',2),
                    (2,1,10,10,'[]',2),(2,1,12,90,'[]',1),
                    (1,2,20,50,'[]',1),(1,3,30,0,'[]',1),(1,4,40,0,'[]',1),(1,5,50,0,'[]',1);
                INSERT INTO {schema}.release_fact VALUES
                    (10,'dump_modification','hacked'),(11,'dump_modification','fixed'),
                    (12,'dump_modification','cracked'),(20,'dump_modification','trained'),
                    (30,'dump_modification','modified'),(30,'dump_modification','undub'),
                    (40,'dump_modification','hacked'),(40,'dump_modification','translated'),
                    (50,'dump_status','bad_or_hacked');
            """)
            for name in ('025_cache_preferred_releases.sql', '027_rom_hack_filter.sql'):
                sql = (PROJECT_ROOT / 'sql/layers/scoring' / name).read_text()
                c.exec_driver_sql(sql.replace('app.', schema + '.').replace('catalog.', schema + '.'))
            filtered = f'{schema}.user_preferred_release_without_hacks'
            fields = 'user_id, software_id, release_id, top_score_tie_count, tie_broken'
            self.assertEqual(c.exec_driver_sql(f'SELECT {fields} FROM {filtered} ORDER BY 1,2').all(), [
                (1,1,11,2,True), (1,2,None,None,None), (1,3,30,1,False),
                (1,4,40,1,False), (1,5,50,1,False), (2,1,12,1,False),
            ])
            winner = f'SELECT release_id FROM {filtered} WHERE user_id=1 AND software_id=1'
            with c.begin_nested() as savepoint:
                c.exec_driver_sql(f"INSERT INTO {schema}.release_fact VALUES (10,'dump_modification','translated')")
                self.assertEqual(c.exec_driver_sql(winner).scalar_one(), 10)
                savepoint.rollback()
            self.assertEqual(c.exec_driver_sql(winner).scalar_one(), 11)
            c.exec_driver_sql(f"UPDATE {schema}.release_fact SET fact_value='modified' WHERE release_id=11")
            self.assertEqual(c.exec_driver_sql(winner).scalar_one(), 12)
            c.exec_driver_sql(f"DELETE FROM {schema}.release_fact WHERE release_id=11")
            self.assertEqual(c.exec_driver_sql(winner).scalar_one(), 11)
            c.exec_driver_sql(f'TRUNCATE {schema}.release_fact')
            self.assertEqual(c.exec_driver_sql(winner).scalar_one(), 10)

    def test_scoring_publication_preserves_winners_ties_and_user_scope(self):
        # A materialized view needs an ordinary source table. The entire
        # private schema is rolled back when this connection closes.
        schema = 'test_preferred_' + uuid4().hex
        sql = (PROJECT_ROOT / 'sql/layers/scoring/025_cache_preferred_releases.sql').read_text()
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        with engine.connect() as c:
            c.exec_driver_sql(f'CREATE SCHEMA {schema}')
            c.exec_driver_sql(f"""
                CREATE TABLE {schema}.user_release_score (
                    user_id bigint, software_id bigint, release_id bigint, score bigint,
                    breakdown jsonb, rank_within_software bigint
                );
                INSERT INTO {schema}.user_release_score VALUES
                    (1,1,9,50,'[]',1),(1,1,4,50,'["region"]',1),(1,1,1,20,'[]',2),
                    (2,1,9,75,'[]',1),(2,1,4,50,'[]',2),(1,2,8,0,'[]',1);
            """)
            publish = sql.replace('app.', schema + '.')
            read = f'SELECT * FROM {schema}.user_preferred_release ORDER BY user_id, software_id'
            c.exec_driver_sql(publish)
            self.assertEqual(c.exec_driver_sql(read).all(), [
                (1, 1, 4, 50, ['region'], 2, True),
                (1, 2, 8, 0, [], 1, False), (2, 1, 9, 75, [], 1, False),
            ])
            c.exec_driver_sql(f'UPDATE {schema}.user_release_score SET rank_within_software=2 WHERE user_id=1 AND release_id=4')
            c.exec_driver_sql(publish)
            self.assertEqual(c.exec_driver_sql(read).first(), (1, 1, 9, 50, [], 1, False))


if __name__ == "__main__":
    unittest.main()
