"""Check reviewed artwork against an isolated catalog and LaunchBox snapshot."""
import json
import os
import unittest

from sqlalchemy import text

from gamedb.catalog.launchbox_media import IMAGE_CANDIDATES_SQL
from gamedb.database import create_database_engine


@unittest.skipUnless(os.environ.get('GAMEDB_TEST_POSTGRES') == '1', 'requires PostgreSQL')
class ReviewedArtworkTests(unittest.TestCase):
    def test_only_unambiguous_missing_artwork_is_selected(self):
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        with engine.connect() as connection:
            connection.exec_driver_sql("""
                CREATE TEMP TABLE system(id int, manufacturer_name text, system_name text);
                CREATE TEMP TABLE software(id int, system_id int);
                CREATE TEMP TABLE release_content_signature(release_id int, sha1_set_digest text);
                CREATE TEMP TABLE software_release(release_id int, software_id int);
                CREATE TEMP TABLE software_fact(id int, software_id int, source_revision text, source_provider text);
                CREATE TEMP TABLE software_fact_evidence(software_fact_id int, source_file_id int, match_details jsonb);
                CREATE TEMP TABLE launchbox_import(id int, imported_at date, source_revision text);
                CREATE TEMP TABLE launchbox_record(import_id int, record_type text, database_id int, raw_record jsonb);
                CREATE TEMP TABLE launchbox_image_import(import_id int);
                CREATE TEMP TABLE launchbox_image(import_id int, database_id int, row_number int, file_name text, image_type text, region text, raw_record jsonb);
                CREATE TEMP TABLE app_user(id int, username text);
                CREATE TEMP TABLE user_preferred_release(user_id int, software_id int, release_id int);
                CREATE TEMP TABLE release_fact(release_id int, fact_key text, fact_value text);
                CREATE TEMP TABLE software_media(software_id int, media_kind text);

                INSERT INTO system VALUES (1,'M','A'), (2,'M','B');
                INSERT INTO software SELECT i, CASE WHEN i=8 THEN 2 ELSE 1 END FROM generate_series(1,8) i;
                INSERT INTO software_release SELECT id,id FROM software;
                INSERT INTO software_release VALUES (9,1), (10,7);
                INSERT INTO release_content_signature VALUES
                    (1,'same'), (9,'same'), (8,'same'), (2,'ambiguous'), (3,'ambiguous'),
                    (4,'claimed'), (5,'metadata'), (6,'foreign'), (7,'first'), (10,'second');
                INSERT INTO launchbox_import VALUES (1,'2000-01-01','old'), (2,'2000-01-02','new');
                INSERT INTO launchbox_image_import VALUES (1),(2);
                INSERT INTO launchbox_record
                    SELECT s.id,'Game',i,jsonb_build_object('Platform','A','Name','Title '||i)
                    FROM launchbox_import s CROSS JOIN generate_series(11,18) i;
                INSERT INTO launchbox_image
                    SELECT s.id,i,i,'cover-'||i,'Box - Front','World'
                    FROM launchbox_import s CROSS JOIN generate_series(11,18) i;
                INSERT INTO launchbox_image VALUES (2,11,99,'logo','Clear Logo','World');
                INSERT INTO launchbox_image VALUES
                    (2,11,100,'r2_verified.png','Screenshot - Gameplay','World','{"CRC32":"123"}'),
                    (2,11,101,'r2_unchecked.png','Screenshot - Game Title','World','{"CRC32":"456"}'),
                    (2,13,102,'r2_replaced.png','Clear Logo','World','{"CRC32":"789"}');
                INSERT INTO app_user VALUES (1,'default');
                INSERT INTO user_preferred_release SELECT 1,id,id FROM software;
                INSERT INTO software_media VALUES (1,'logo');
                INSERT INTO software_fact VALUES (1,5,'new','launchbox');
                INSERT INTO software_fact_evidence VALUES (1,2,'{"database_id": 13}');
            """)
            reviews = [
                ('same', 11, 'A'), ('ambiguous', 12, 'A'), ('claimed', 13, 'A'),
                ('metadata', 14, 'A'), ('foreign', 15, 'B'),
                ('first', 16, 'A'), ('second', 17, 'A'),
            ]
            records = [
                dict(manufacturer_name='M', system_name='A', release_content_signature=sig,
                     launchbox_database_id=game_id, launchbox_platform=platform,
                     launchbox_title=f'Title {game_id}')
                for sig, game_id, platform in reviews
            ]
            records.append(dict(
                manufacturer_name='M', system_name='A', release_content_signature='foreign',
                launchbox_database_id=18, launchbox_platform='A', launchbox_title='Old title',
            ))
            for record in records:
                if record['launchbox_database_id'] == 11:
                    record.update(verified_file_name='r2_verified.png', verified_crc32='123')
                if record['launchbox_database_id'] == 13:
                    record.update(verified_file_name='r2_replaced.png', verified_crc32='987')
            query = IMAGE_CANDIDATES_SQL
            for schema in ('catalog.', 'app.', 'staging.'):
                query = query.replace(schema, 'pg_temp.')
            results = connection.execute(text(query), {
                'reviewed': json.dumps(records), 'username': 'default',
            })
            self.assertEqual(sorted(
                (r.software_id, r.basis, r.import_id, r.file_name) for r in results
            ), [
                (1, 'launchbox_reviewed', 2, 'cover-11'),
                (1, 'launchbox_reviewed', 2, 'r2_verified.png'),
                (5, 'launchbox_metadata', 2, 'cover-13'),
            ])
