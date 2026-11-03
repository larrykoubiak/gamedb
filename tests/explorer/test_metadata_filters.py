"""Metadata facets share the title search's selected claims and software scope."""
import os
import unittest

from gamedb.database import create_database_engine
from gamedb.explorer.repository import CatalogRepository, validate_metadata_filters
from gamedb.explorer.server import _metadata_filters


class MetadataFilterValidationTests(unittest.TestCase):
    def test_rejects_unknown_fields_and_unbounded_values(self):
        for filters in ([], {'description': ['text']}, {'genre': 'Action'},
                        {'genre': ['']}, {'genre': [1]}, {'genre': ['x'] * 26},
                        {'developer': ['x' * 1001]}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                validate_metadata_filters(filters)
        self.assertEqual(validate_metadata_filters({'genre': ['Action', 'Action'], 'tags': []}),
                         {'genre': ['Action']})
        for raw in ('{bad', '[]', 'x' * 16001):
            with self.assertRaises(ValueError):
                _metadata_filters({'filters': [raw]})

    def test_filter_values_are_sql_literals_and_description_is_not_a_facet(self):
        repository = CatalogRepository('default')
        sql = repository.titles_sql(None, 20, 0, metadata_filters={'publisher': ["Bob's Studio"]})
        self.assertIn("'Bob''s Studio'", sql)
        self.assertIn('filter_fact.is_selected', sql)
        with self.assertRaises(ValueError):
            repository.metadata_options_sql('description')


@unittest.skipUnless(os.environ.get('GAMEDB_TEST_POSTGRES') == '1', 'requires PostgreSQL')
class MetadataFilterQueryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_database_engine()
        self.c = self.engine.connect()
        self.transaction = self.c.begin()
        self.repository = CatalogRepository('test')
        self.c.exec_driver_sql('''
            CREATE TEMP TABLE system (id bigint, manufacturer_name text, system_name text) ON COMMIT DROP;
            CREATE TEMP TABLE software (id bigint, system_id bigint, preferred_title_id bigint,
                display_name text, identity_basis text) ON COMMIT DROP;
            CREATE TEMP TABLE title (id bigint, display_title text) ON COMMIT DROP;
            CREATE TEMP TABLE release (id bigint, title_id bigint) ON COMMIT DROP;
            CREATE TEMP TABLE software_release (software_id bigint, release_id bigint) ON COMMIT DROP;
            CREATE TEMP TABLE app_user (id bigint, username text) ON COMMIT DROP;
            CREATE TEMP TABLE user_preferred_release (user_id bigint, software_id bigint,
                release_id bigint, score int DEFAULT 0, breakdown jsonb DEFAULT '[]',
                top_score_tie_count int DEFAULT 1, tie_broken boolean DEFAULT false) ON COMMIT DROP;
            CREATE TEMP TABLE software_fact (software_id bigint, fact_key text, fact_value text,
                is_selected boolean) ON COMMIT DROP;
            INSERT INTO system VALUES (1,'Nintendo','NES'), (2,'Sega','Mega Drive');
            INSERT INTO software VALUES (1,1,101,'Mario','title_fallback'),
                (2,1,102,'Zelda','title_fallback'), (3,2,103,'Sonic','title_fallback'),
                (4,1,104,'Not in this user library','title_fallback'),
                (5,1,105,'Shooter','title_fallback');
            INSERT INTO title VALUES (101,'Mario'),(102,'Zelda'),(103,'Sonic'),
                (104,'Not in this user library'),(105,'Shooter'),(106,'Mario alternate');
            INSERT INTO release VALUES (1,101),(2,102),(3,103),(4,104),(5,105),(6,106);
            INSERT INTO software_release VALUES (1,1),(2,2),(3,3),(4,4),(5,5),(2,6);
            INSERT INTO app_user VALUES (1,'test'),(2,'someone-else');
            INSERT INTO user_preferred_release (user_id,software_id,release_id)
                VALUES (1,1,1),(1,2,2),(1,3,3),(2,4,4),(1,5,5);
            INSERT INTO software_fact VALUES
                (1,'genre','Action',true),(1,'genre','Action',true),(1,'genre','Platform',true),
                (1,'developer','Nintendo',true),(1,'publisher','Bob''s Studio',true),
                (2,'genre','Adventure',true),(2,'developer','Nintendo',true),
                (3,'genre','Action',true),(3,'developer','Sonic Team',true),
                (3,'developer','Nintendo',false),(4,'genre','Action',true),
                (5,'genre','Action',false),(5,'genre','Shooter',true);
        ''')

    def tearDown(self):
        self.transaction.rollback()
        self.c.close()
        self.engine.dispose()

    def execute(self, sql):
        return self.c.exec_driver_sql(sql.replace('catalog.', 'pg_temp.').replace('app.', 'pg_temp.')).scalar_one()

    def ids(self, filters=None, system_id=None, query=''):
        scope = self.repository.software_scope_sql(system_id, query, filters)
        return self.execute('WITH ' + scope + ' SELECT array_agg(software_id ORDER BY software_id) FROM chosen') or []

    def test_any_value_within_field_all_fields_together_and_selected_sources_only(self):
        self.assertEqual(self.ids({'genre': ['Action', 'Adventure']}), [1, 2, 3])
        self.assertEqual(self.ids({'genre': ['Action'], 'developer': ['Nintendo']}), [1])
        self.assertEqual(self.ids({'genre': ['Adventure'], 'developer': ['Nintendo']}), [2])
        self.assertEqual(self.ids({'publisher': ["Bob's Studio"]}), [1])
        self.assertEqual(self.ids({'genre': ['action']}), [])

    def test_platform_and_alternate_title_search_combine_with_metadata(self):
        self.assertEqual(self.ids({'genre': ['Action']}, 1, 'Mario'), [1])
        self.assertEqual(self.ids({'genre': ['Adventure']}, 1, 'Mario'), [2])
        self.assertEqual(self.ids({'genre': ['Action']}, 2, 'Mario'), [])

    def test_placeholder_like_search_and_filter_values_remain_literals(self):
        self.assertEqual(self.ids({'genre': ['Action']}, 1, '__METADATA_PREDICATES__'), [])
        options = self.execute(self.repository.metadata_options_sql('genre', metadata_filters={
            'developer': ['__OPTION_SEARCH__'],
        }))
        self.assertEqual(options, {'total': 0, 'items': []})

    def test_options_count_software_once_and_ignore_only_their_own_filter(self):
        options = self.execute(self.repository.metadata_options_sql('genre', 1, '',
            {'genre': ['Action'], 'developer': ['Nintendo']}))
        self.assertEqual(options, {'total': 3, 'items': [
            {'value': 'Action', 'count': 1}, {'value': 'Adventure', 'count': 1},
            {'value': 'Platform', 'count': 1}]})
        options = self.execute(self.repository.metadata_options_sql('developer', None, '',
            {'genre': ['Action'], 'developer': ['Nintendo']}, 'sonic'))
        self.assertEqual(options, {'total': 1, 'items': [{'value': 'Sonic Team', 'count': 1}]})
        self.assertEqual(self.execute(self.repository.metadata_options_sql('genre', 2, 'Mario')),
                         {'total': 0, 'items': []})

    def test_value_search_is_bounded_for_large_lists(self):
        self.c.exec_driver_sql("INSERT INTO software_fact SELECT 1,'developer','Studio ' || n,true FROM generate_series(1,150) n")
        options = self.execute(self.repository.metadata_options_sql('developer', search='Studio '))
        self.assertEqual(options['total'], 150)
        self.assertEqual(len(options['items']), 100)
