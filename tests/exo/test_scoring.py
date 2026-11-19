import os
import unittest
from pathlib import Path

from gamedb.database import create_database_engine

SCORING = Path(__file__).resolve().parents[2] / "sql/layers/exo/scoring.sql"


@unittest.skipUnless(
    os.environ.get("GAMEDB_TEST_POSTGRES") == "1", "requires PostgreSQL"
)
class EditionScoringTests(unittest.TestCase):
    def test_source_and_hardware_preferences_respect_personal_weights_and_filter(self):
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        with engine.connect() as connection:
            execute = connection.exec_driver_sql
            execute("""
                CREATE TEMP TABLE app_user (id bigint, username text);
                CREATE TEMP TABLE user_preference (
                    id bigint GENERATED ALWAYS AS IDENTITY, user_id bigint, fact_key text, match_operator text,
                    fact_value text, score int, enabled boolean DEFAULT true, description text,
                    system_manufacturer text, system_name text,
                    CONSTRAINT user_preference_rule_scope_key UNIQUE NULLS NOT DISTINCT
                        (user_id,fact_key,match_operator,fact_value,system_manufacturer,system_name));
                CREATE TEMP TABLE system (id bigint, manufacturer_name text, system_name text);
                CREATE TEMP TABLE exo_entry (entry_key text, source_list text, fields jsonb);
                CREATE TEMP TABLE exo_edition (entry_key text, edition_key text, work_key text,
                    label text, selection text, environment text, system_id bigint, is_mod boolean);
                CREATE TEMP TABLE exo_browse (entry_key text, work_key text, scope_id bigint,
                    software_id bigint, system_id bigint, system_name text);
                CREATE TEMP TABLE exo_shelf (id bigint, name text);
                INSERT INTO app_user VALUES (1,'default'),(2,'another user');
                INSERT INTO system VALUES (1,'IBM','PC Compatibles'),(2,'Apple','Macintosh');
                INSERT INTO exo_entry VALUES ('game','ScummVM','{}'),('mod','MS-DOS','{}');
                INSERT INTO exo_edition VALUES
                    ('game','pc','one','DOS version','DOS','MS-DOS',1,false),
                    ('game','mac','one','Mac version','Mac','Macintosh',2,false),
                    ('mod','modded','two','Gameplay hack','','MS-DOS',1,true);
                INSERT INTO exo_browse VALUES ('game','one',1,11,1,'PC Compatibles'),
                    ('game','one',2,12,2,'Macintosh'),('game','one',7,17,NULL,'ScummVM'),
                    ('mod','two',1,18,1,'PC Compatibles');
                INSERT INTO exo_shelf VALUES (7,'ScummVM');
                INSERT INTO user_preference (user_id,fact_key,match_operator,fact_value,score,description)
                    VALUES (1,'dump_modification','equals','hacked',-200,'Demote gameplay hacks');
            """)
            install = (
                SCORING.read_text()
                .replace("app.", "pg_temp.")
                .replace("catalog.", "pg_temp.")
            )
            install = install.replace("gamedb:exo:catalog", "gamedb:test:exo:scores")
            execute(install)
            refresh = "SELECT pg_temp.refresh_exo_scores()"
            execute(refresh)
            scores = "SELECT edition_key,score FROM pg_temp.exo_edition_score WHERE user_id=1 ORDER BY 1"
            self.assertEqual(
                execute(scores).all(), [("mac", 75), ("modded", -50), ("pc", 150)]
            )
            self.assertEqual(
                execute(
                    "SELECT DISTINCT score FROM pg_temp.exo_edition_score WHERE user_id=2"
                )
                .scalars()
                .all(),
                [0],
            )
            self.assertEqual(
                execute("""
                SELECT scope_id,edition_key FROM pg_temp.exo_browse_choice
                WHERE user_id=1 AND hide_mods ORDER BY scope_id
            """).all(),
                [(1, "pc"), (2, "mac"), (7, "pc")],
            )
            reason_scores = execute("""
                SELECT breakdown FROM pg_temp.exo_edition_score WHERE user_id=1 AND edition_key='pc'
            """).scalar_one()
            self.assertEqual([reason["score"] for reason in reason_scores], [75, 75])
            generation = (
                "SELECT signature FROM pg_temp.exo_score_generation WHERE user_id=1"
            )
            before = execute(generation).scalar_one()
            execute("""UPDATE pg_temp.user_preference SET enabled=false
                       WHERE fact_value='eXo' AND system_name IS NOT NULL""")
            execute(install)
            execute(refresh)
            self.assertEqual(
                execute(scores).all(), [("mac", 75), ("modded", -125), ("pc", 75)]
            )
            self.assertNotEqual(execute(generation).scalar_one(), before)
            self.assertEqual(
                execute("""
                SELECT tie_count FROM pg_temp.exo_browse_choice
                WHERE user_id=1 AND scope_id=7 AND hide_mods
            """).scalar_one(),
                2,
            )
