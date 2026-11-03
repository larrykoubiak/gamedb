"""Exercise scoring and both API queries against isolated PostgreSQL temp tables.

Set GAMEDB_TEST_POSTGRES=1 to run using the configured database connection.
"""
import os
from pathlib import Path
import unittest

from sqlalchemy import text

from gamedb.database import create_database_engine

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('GAMEDB_TEST_POSTGRES') == '1', 'requires PostgreSQL')
class MetadataScoringTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_database_engine()
        self.c = self.engine.connect()
        self.transaction = self.c.begin()
        self.c.exec_driver_sql('''CREATE TEMP TABLE software_fact (
            id bigint GENERATED ALWAYS AS IDENTITY, software_id bigint DEFAULT 1,
            fact_key text, fact_value text, source_provider text,
            source_revision text DEFAULT 'test', matched_content_count bigint,
            source_record_count bigint, value_rank bigint, value_count bigint,
            source_score integer DEFAULT 0, is_selected boolean DEFAULT false
        ) ON COMMIT DROP;
        CREATE TEMP TABLE software (id bigint, system_id bigint) ON COMMIT DROP;
        INSERT INTO software VALUES (1,1);
        CREATE TEMP TABLE software_fact_evidence (
            software_fact_id bigint, source_database text, match_method text, match_details jsonb
        ) ON COMMIT DROP;
        INSERT INTO software_fact (fact_key,fact_value,source_provider,matched_content_count,source_record_count)
        VALUES ('developer','RDB Studio','libretro-database',99,100),
               ('developer','LaunchBox Studio','launchbox',0,1),
               ('publisher','Fallback Publisher','libretro-database',2,3),
               ('genre','Action','launchbox',0,1),
               ('genre','Platform','launchbox',0,1),
               ('genre','Shooter','libretro-database',10,10),
               ('player_count','2','libretro-database',4,4),
               ('player_count','2','launchbox',0,1),
               ('origin','B','libretro-database',1,1),
               ('origin','A','libretro-database',1,1);''')
        self.c.exec_driver_sql(self.sql('sql/layers/metadata/030_rank.sql'))

    def tearDown(self):
        self.transaction.rollback()
        self.c.close()
        self.engine.dispose()

    def sql(self, path):
        return (ROOT / path).read_text().replace('catalog.software_fact_evidence', 'pg_temp.software_fact_evidence').replace('catalog.software_fact', 'pg_temp.software_fact').replace('catalog.software ', 'pg_temp.software ')

    def test_preference_fallback_multivalued_genres_and_stable_ties(self):
        selected = self.c.execute(text('''SELECT fact_key,fact_value,source_score
            FROM pg_temp.software_fact WHERE is_selected ORDER BY fact_key,fact_value''')).all()
        self.assertEqual(selected, [('developer','LaunchBox Studio',100),
                                   ('genre','Action',100), ('genre','Platform',100),
                                   ('origin','A',50), ('player_count','2',100),
                                   ('publisher','Fallback Publisher',50)])
        self.assertEqual(self.c.execute(text('SELECT count(*) FROM pg_temp.software_fact')).scalar_one(), 10)

    def test_single_and_snapshot_api_agree_and_keep_provenance(self):
        single = self.c.execute(text(self.sql('sql/queries/explorer/software_facts.sql').replace('__SOFTWARE_ID__','1'))).scalar_one()
        snapshot = self.c.execute(text(self.sql('sql/queries/explorer/system_software_facts.sql').replace('__SYSTEM_ID__','1'))).scalar_one()
        self.assertEqual(single, snapshot['1'])
        facts = {f['key']: f for f in single}
        self.assertEqual(facts['developer']['preferredValues'], ['LaunchBox Studio'])
        self.assertEqual(facts['genre']['preferredValues'], ['Action','Platform'])
        claims = facts['player_count']['values']
        self.assertEqual(len(claims), 2)
        self.assertEqual([v['sourceScore'] for v in claims], [100,50])
        self.assertEqual([v['selected'] for v in claims], [True,False])
        self.assertEqual(facts['player_count']['preferredValues'], ['2'])
