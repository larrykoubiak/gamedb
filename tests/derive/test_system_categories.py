"""Reviewed categories and their reference-to-explorer database contract."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import TextClause

from gamedb.database import create_database_engine
from gamedb.derive.extractors.reference_extract import ReferenceExtractor
from gamedb.derive.schema import metadata

ROOT = Path(__file__).resolve().parents[2]


class SystemCategoryTests(unittest.TestCase):
    def test_categories_cover_every_system_and_keep_media_independent_policies(self):
        rows = ReferenceExtractor(ROOT / 'reference')._rows('canonical_systems.csv')
        categories = {
            (row['canonical_manufacturer_name'], row['canonical_system_name']): row['category']
            for row in rows
        }
        self.assertEqual(len(categories), len(rows))
        self.assertEqual(set(categories.values()), {'console', 'handheld', 'computer', 'arcade', 'other'})
        for identity, expected in {
            ('Nintendo', 'Famicom Disk System'): 'console',
            ('Sony', 'PlayStation 3'): 'console',
            ('MSX', 'MSX'): 'computer',
            ('Nintendo', 'Game Boy'): 'handheld',
            ('Capcom', 'CP System III'): 'arcade',
            ('Multi-format', 'Compilations'): 'other',
        }.items():
            self.assertEqual(categories[identity], expected)
        self.assertTrue(all(category in {'console', 'handheld', 'computer', 'arcade', 'other'}
                            for category in categories.values()))

    def test_missing_or_invalid_categories_fail_before_database_changes(self):
        for value in (None, '', 'disc', 'Console'):
            row = {'canonical_manufacturer_name': 'Example', 'canonical_system_name': 'Test'}
            if value is not None:
                row['category'] = value
            connection = MagicMock()
            extractor = ReferenceExtractor(ROOT / 'reference')
            with patch.object(extractor, '_rows', return_value=[row]):
                with self.assertRaisesRegex(ValueError, 'Example / Test'):
                    extractor.execute(connection)
            connection.execute.assert_not_called()

    @unittest.skipUnless(os.environ.get('GAMEDB_TEST_POSTGRES') == '1', 'requires PostgreSQL')
    def test_old_reference_schema_rebuild_projects_categories_into_systems_api(self):
        # All DDL and data live in unique schemas and are rolled back. No live
        # reference, derived, catalog, or user preference tables are changed.
        engine = create_database_engine()
        reference_schema = 'test_categories_' + uuid4().hex
        catalog_schema = reference_schema + '_catalog'
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA {reference_schema}'))
                connection.execute(text(f'CREATE SCHEMA {catalog_schema}'))
                translated = connection.execution_options(schema_translate_map={'ref': reference_schema})
                metadata.create_all(translated, tables=[t for t in metadata.sorted_tables if t.schema == 'ref'])
                connection.execute(text(f'ALTER TABLE {reference_schema}.canonical_system DROP COLUMN category'))

                def execute(statement, *args, **kwargs):
                    if isinstance(statement, TextClause):
                        statement = text(str(statement).replace('ref.', reference_schema + '.'))
                    return translated.execute(statement, *args, **kwargs)

                # Exercise upgrading a pre-category schema and repeatability.
                extractor = ReferenceExtractor(ROOT / 'reference')
                for _ in range(2):
                    extractor.execute(SimpleNamespace(execute=execute))
                nulls = connection.execute(text(f'SELECT count(*) FROM {reference_schema}.canonical_system WHERE category IS NULL')).scalar_one()
                self.assertEqual(nulls, 0)

                source = (ROOT / 'sql/layers/catalog/010_schema_and_releases.sql').read_text()
                create_system = source[source.index('CREATE TABLE catalog.system'):source.index('CREATE TABLE catalog.title')]
                insert_system = source[source.index('INSERT INTO catalog.system'):source.index('INSERT INTO catalog.title')]
                for statement in (create_system, insert_system):
                    connection.execute(text(statement.replace('catalog.', catalog_schema + '.').replace('ref.', reference_schema + '.')))
                for table in (f'{reference_schema}.canonical_system', f'{catalog_schema}.system'):
                    for category in (None, 'disc'):
                        with self.assertRaises(IntegrityError):
                            with connection.begin_nested():
                                connection.execute(text(f'UPDATE {table} SET category = :category'), {'category': category})
                connection.execute(text('''
                    CREATE TEMP TABLE software (id bigint, system_id bigint) ON COMMIT DROP;
                    CREATE TEMP TABLE user_preferred_release (software_id bigint, user_id bigint) ON COMMIT DROP;
                    CREATE TEMP TABLE app_user (id bigint, username text) ON COMMIT DROP;
                    INSERT INTO app_user VALUES (1, 'test'), (2, 'someone-else');
                '''))
                connection.execute(text(f'''
                    INSERT INTO software SELECT id, id FROM {catalog_schema}.system;
                    INSERT INTO user_preferred_release SELECT id, 1 FROM software;
                '''))
                query = (ROOT / 'sql/queries/explorer/systems.sql').read_text()
                query = query.replace('catalog.system ', catalog_schema + '.system ')
                query = query.replace('catalog.software ', 'pg_temp.software ').replace('app.', 'pg_temp.')
                query = query.replace('__USERNAME__', "'test'")
                systems = connection.execute(text(query)).scalar_one()
                expected = extractor._rows('canonical_systems.csv')
                self.assertEqual(len(systems), len(expected))
                self.assertEqual(
                    {(s['manufacturer'], s['name']): s['category'] for s in systems},
                    {(s['canonical_manufacturer_name'], s['canonical_system_name']): s['category'] for s in expected},
                )
                self.assertTrue(all(s['gameCount'] == 1 for s in systems))
            finally:
                transaction.rollback()
        engine.dispose()
