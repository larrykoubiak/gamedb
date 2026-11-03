from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest

from sqlalchemy import text

from gamedb.catalog.genres import genre_values, normalize_genres, read_genre_aliases
from gamedb.database import create_database_engine

ROOT = Path(__file__).resolve().parents[2]


class GenreTests(unittest.TestCase):
    def setUp(self):
        self.aliases = read_genre_aliases(ROOT / 'reference/genre_aliases.csv')

    def test_launchbox_lists_split_and_aliases_deduplicate(self):
        self.assertEqual(genre_values(' Action; Role-Playing; RPG; ;Action ', 'launchbox', self.aliases),
                         ['Action', 'Role-Playing'])

    def test_providers_share_canonical_names(self):
        for rdb, launchbox in [('Role-playing (RPG)', 'Role-Playing'),
                               ('Educational', 'Education'), ('Board', 'Board Game'),
                               ('Gambling Games', 'Casino'), ("Beat'em Up", "Beat 'em Up")]:
            self.assertEqual(genre_values(rdb, 'libretro-database', self.aliases),
                             genre_values(launchbox, 'launchbox', self.aliases))

    def test_rdb_lists_and_explicit_hierarchy_aliases(self):
        self.assertEqual(genre_values('Board / Card', 'libretro-database', self.aliases),
                         ['Board Game', 'Card Game'])
        self.assertEqual(genre_values('Arcade: Shoot-em-up', 'libretro-database', self.aliases),
                         ["Shoot 'em Up"])

    def test_distinct_subgenres_and_unknown_names_survive(self):
        value = 'Shooter; Shoot \'em Up; Flight Simulator; Vehicle Simulation; Future Genre'
        self.assertEqual(len(genre_values(value, 'launchbox', self.aliases)), 5)
        self.assertEqual(genre_values('Utility: Copy/Backup', 'libretro-database', self.aliases),
                         ['Utility: Copy/Backup'])

    def test_alias_case_and_unicode_normalization(self):
        self.assertEqual(genre_values(' ＲＰＧ ', 'launchbox', self.aliases), ['Role-Playing'])

    def test_conflicting_aliases_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'aliases.csv'
            path.write_text('alias,canonical_genre\nRPG,Role-Playing\nrpg,Adventure\n')
            with self.assertRaises(ValueError):
                read_genre_aliases(path)


@unittest.skipUnless(os.environ.get('GAMEDB_TEST_POSTGRES') == '1', 'requires PostgreSQL')
class GenreDatabaseTests(unittest.TestCase):
    def test_alias_merging_preserves_provider_claims_counts_and_original_evidence(self):
        engine = create_database_engine()
        with engine.connect() as c:
            transaction = c.begin()
            try:
                c.exec_driver_sql('''
                    CREATE TEMP TABLE software_fact (
                        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        software_id bigint, fact_key text, fact_value text,
                        source_provider text, source_revision text,
                        source_record_count bigint, matched_content_count bigint,
                        value_rank bigint, value_count bigint
                    ) ON COMMIT DROP;
                    CREATE TEMP TABLE software_fact_evidence (
                        software_fact_id bigint REFERENCES software_fact(id) ON DELETE CASCADE,
                        source_file_id bigint, source_row_number bigint,
                        source_database text, source_relative_path text,
                        matched_sha1 text, match_method text, match_details jsonb,
                        PRIMARY KEY (software_fact_id, source_file_id, source_row_number)
                    ) ON COMMIT DROP;
                    INSERT INTO software_fact (
                        software_id, fact_key, fact_value, source_provider, source_revision
                    ) VALUES (1,'genre','RPG / Board','libretro-database','rdb'),
                        (1,'genre','Role-playing (RPG)','libretro-database','rdb'),
                        (1,'genre','Role-Playing; Action','launchbox','lb');
                    INSERT INTO software_fact_evidence VALUES
                        (1,1,1,'rdb','one','a','exact_sha1','{}'),
                        (1,1,2,'rdb','two','b','exact_sha1','{}'),
                        (2,1,1,'rdb','one','a','exact_sha1','{}'),
                        (3,2,3,'lb','Metadata.xml',NULL,'title','{}');
                ''')

                def execute(statement, *args):
                    return c.execute(text(str(statement).replace('catalog.', 'pg_temp.')), *args)

                normalize_genres(SimpleNamespace(
                    execute=execute,
                    exec_driver_sql=lambda sql: c.exec_driver_sql(sql.replace('catalog.', 'pg_temp.')),
                ), ROOT)
                facts = c.exec_driver_sql('''SELECT fact_value,source_provider,
                    source_record_count,matched_content_count FROM pg_temp.software_fact
                    ORDER BY source_provider,fact_value''').all()
                self.assertEqual(facts, [
                    ('Action', 'launchbox', 1, 0), ('Role-Playing', 'launchbox', 1, 0),
                    ('Board Game', 'libretro-database', 2, 2),
                    ('Role-Playing', 'libretro-database', 2, 2),
                ])
                evidence = c.exec_driver_sql('''SELECT e.match_details->'original_genres'
                    FROM pg_temp.software_fact_evidence e
                    JOIN pg_temp.software_fact f ON f.id=e.software_fact_id
                    WHERE f.fact_value='Role-Playing' AND f.source_provider='libretro-database'
                      AND e.source_row_number=1''').scalar_one()
                self.assertEqual(set(evidence), {'RPG / Board', 'Role-playing (RPG)'})
                self.assertEqual(c.exec_driver_sql('''SELECT count(*) FROM (
                    SELECT f.id FROM pg_temp.software_fact f
                    JOIN pg_temp.software_fact_evidence e ON e.software_fact_id=f.id
                    GROUP BY f.id,f.source_record_count
                    HAVING count(*) <> f.source_record_count
                ) invalid''').scalar_one(), 0)
            finally:
                transaction.rollback()
        engine.dispose()
