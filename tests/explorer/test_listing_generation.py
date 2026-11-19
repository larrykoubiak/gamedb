import os
from pathlib import Path
import unittest

from gamedb.catalog.metadata import sql_body
from gamedb.database import create_database_engine
from gamedb.explorer.repository import CatalogRepository


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('GAMEDB_TEST_POSTGRES') == '1', 'requires PostgreSQL')
class ListingGenerationTests(unittest.TestCase):
    def test_pooled_listing_reads_reuse_a_connection_and_preserve_literal_percents(self):
        engine = create_database_engine(pool_pre_ping=True)
        self.addCleanup(engine.dispose)
        repository = CatalogRepository('test', listing_engine=engine)
        query = "SELECT jsonb_build_object('title', '100% %(name)s', 'pid', pg_backend_pid())"
        first = repository._read_listing(query)
        self.assertEqual(first['title'], '100% %(name)s')
        self.assertEqual(repository._read_listing(query), first)

    def test_publications_invalidate_listings_and_rolled_back_edits_do_not(self):
        install = sql_body(ROOT / 'sql/layers/metadata/095_listing_generation.sql').replace('catalog.', 'pg_temp.')
        revision = CatalogRepository('test').catalog_revision_sql().replace('catalog.', 'pg_temp.').replace('app.', 'pg_temp.')
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        with engine.connect() as c:
            c.exec_driver_sql("""
                CREATE TEMP TABLE app_user (id int, username text);
                CREATE TEMP TABLE user_score_generation (user_id int, generated_at timestamptz, preference_signature text);
                CREATE TEMP TABLE media_generation (singleton boolean, signature text);
                CREATE TEMP TABLE exo_publication (singleton boolean, revision text);
                INSERT INTO exo_publication VALUES (true, 'first eXo');
                CREATE TEMP TABLE exo_score_generation (user_id bigint, signature text);
                INSERT INTO exo_score_generation VALUES (1, 'first eXo scores');
                CREATE TEMP TABLE software_fact (value text);
                CREATE TEMP TABLE software_fact_evidence (value text);
                CREATE TEMP TABLE arcade_release (value text);
                CREATE TEMP TABLE release_fact (value text);
                INSERT INTO app_user VALUES (1, 'test');
                INSERT INTO user_score_generation VALUES (1, now(), 'scoring');
                INSERT INTO media_generation VALUES (true, 'art');
                INSERT INTO software_fact VALUES ('old description');
            """)
            c.exec_driver_sql(install)
            c.commit()

            def current():
                return c.exec_driver_sql(revision).scalar_one()['catalogRevision']

            before = current()
            c.exec_driver_sql("UPDATE pg_temp.software_fact SET value='new description'")
            self.assertNotEqual(current(), before)
            c.rollback()
            self.assertEqual(current(), before)

            for change in (
                "UPDATE pg_temp.software_fact SET value='new description'",
                "INSERT INTO pg_temp.software_fact_evidence VALUES ('source')",
                "INSERT INTO pg_temp.arcade_release VALUES ('new plan')",
                "TRUNCATE pg_temp.release_fact",
                "UPDATE pg_temp.user_score_generation SET preference_signature='changed'",
                "UPDATE pg_temp.user_score_generation SET generated_at=now()",
                "UPDATE pg_temp.media_generation SET signature='new art'",
                "UPDATE pg_temp.exo_publication SET revision='another eXo snapshot'",
                "UPDATE pg_temp.exo_score_generation SET signature='other eXo weights'",
                install,
            ):
                with self.subTest(change=change[:60]):
                    c.exec_driver_sql(change)
                    c.commit()
                    after = current()
                    self.assertNotEqual(before, after)
                    before = after
