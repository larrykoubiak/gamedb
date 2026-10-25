import unittest
from pathlib import Path

from gamedb.catalog.metadata import sql_body
from gamedb.catalog.workflow.config import WorkflowConfig
from gamedb.catalog.workflow.steps import BuildMetadataStep, StepFactory

ROOT = Path(__file__).resolve().parents[2]


class MetadataBuilderTests(unittest.TestCase):
    def test_metadata_pipeline_runs_atomic_multi_provider_builder(self):
        config = WorkflowConfig.load(ROOT / 'pipeline.yml').select(layers=('metadata',))
        self.assertEqual(len(config.layers[0].steps), 1)
        self.assertIsInstance(StepFactory.build(config.layers[0].steps[0]), BuildMetadataStep)

    def test_sql_scripts_leave_transaction_and_optional_sources_to_builder(self):
        for name in ('010_schema.sql', '020_build.sql', '090_indexes_and_validation.sql'):
            sql = sql_body(ROOT / 'sql/layers/metadata' / name)
            self.assertNotIn('\\if', sql)
            self.assertNotIn('\\gset', sql)
            self.assertNotIn('\nBEGIN;', sql)
            self.assertNotIn('\nCOMMIT;', sql)
        self.assertIn('RAISE EXCEPTION', sql)



if __name__ == '__main__':
    unittest.main()
