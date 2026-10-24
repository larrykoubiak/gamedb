import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from gamedb.derive.__main__ import main
from gamedb.derive.pipeline import DerivationPipeline


class DerivationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = DerivationPipeline(engine=object())

    def test_manifest_tells_the_dependency_story(self):
        self.assertEqual(
            self.pipeline.layer_names,
            (
                "schema", "reference", "dat", "system", "inventory",
                "translation_titles", "paths", "names", "releases", "arcade",
            ),
        )

    def test_path_resolution_can_be_selected_alone(self):
        selected = self.pipeline.select(exact=("paths",))

        self.assertEqual(tuple(layer.name for layer in selected), ("paths",))

    def test_name_change_selects_only_interpretation_and_releases(self):
        selected = self.pipeline.select(from_layer="names")

        self.assertEqual(
            tuple(layer.name for layer in selected), ("names", "releases", "arcade")
        )

    def test_plan_exposes_reads_and_writes(self):
        description = self.pipeline.describe(
            self.pipeline.select(exact=("inventory",))
        )

        self.assertIn(
            "reads: staging.rv_files, staging.integrated_package, "
            "staging.integrated_file, derived.dat",
            description,
        )
        self.assertIn(
            "writes: derived.archive_name, derived.package, derived.file",
            description,
        )

    def test_execution_requires_an_explicit_scope(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            main([])

    def test_plan_does_not_create_a_database_engine(self):
        with redirect_stdout(StringIO()), patch(
            "gamedb.derive.__main__.create_database_engine",
            side_effect=AssertionError("plan should not create an engine"),
        ):
            self.assertEqual(main(["--plan"]), 0)
