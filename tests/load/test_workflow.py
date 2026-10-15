import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from gamedb.load.workflow import RebuildWorkflow, WorkflowConfig
from gamedb.load.workflow.steps import ArchiveNamesStep, RunSqlStep, WorkflowContext


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class NonClosingStringIO(StringIO):
    def close(self):
        pass


class WorkflowConfigTests(unittest.TestCase):
    def test_project_pipeline_tells_the_ordered_layer_story(self):
        config = WorkflowConfig.load(PROJECT_ROOT / "pipeline.yml")

        self.assertEqual(
            config.layer_names,
            (
                "reset", "reference", "archive_names", "catalog", "facts",
                "identity", "scoring",
            ),
        )
        self.assertEqual(config.layers[-1].steps[0].name, "build_release_scores")

    def test_exact_layer_selection_retains_pipeline_order(self):
        config = WorkflowConfig.load(PROJECT_ROOT / "pipeline.yml")

        selected = config.select(layers=("scoring", "catalog"))

        self.assertEqual(selected.layer_names, ("catalog", "scoring"))

    def test_layer_range_is_inclusive(self):
        config = WorkflowConfig.load(PROJECT_ROOT / "pipeline.yml")

        selected = config.select(from_layer="archive_names", through_layer="catalog")

        self.assertEqual(selected.layer_names, ("archive_names", "catalog"))

    def test_unknown_layer_is_rejected(self):
        config = WorkflowConfig.load(PROJECT_ROOT / "pipeline.yml")

        with self.assertRaisesRegex(ValueError, "Unknown pipeline layer"):
            config.select(layers=("missing",))

    def test_pipeline_rejects_duplicate_step_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sql = root / "step.sql"
            sql.write_text("select 1;", encoding="utf-8")
            pipeline = root / "pipeline.yml"
            pipeline.write_text(
                """name: duplicate
layers:
  - name: one
    description: first
    steps:
      - {name: repeated, type: run_sql, files: [step.sql]}
  - name: two
    description: second
    steps:
      - {name: repeated, type: run_sql, files: [step.sql]}
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Duplicate pipeline step"):
                WorkflowConfig.load(pipeline)


class WorkflowStepTests(unittest.TestCase):
    @patch("gamedb.load.workflow.steps.subprocess.Popen")
    def test_sql_step_executes_files_in_one_psql_process(self, popen):
        files = (PROJECT_ROOT / "first.sql", PROJECT_ROOT / "second.sql")
        context = WorkflowContext(PROJECT_ROOT)
        process = MagicMock()
        process.stdin = NonClosingStringIO()
        process.stdout = StringIO(
            "__GAMEDB_SQL_FILE_COMPLETE__:1:first.sql\n"
            "__GAMEDB_SQL_FILE_COMPLETE__:2:second.sql\n"
        )
        process.wait.return_value = 0
        popen.return_value = process

        with redirect_stdout(StringIO()):
            RunSqlStep("sql", files).execute(context)

        popen.assert_called_once_with(
            ["psql", "-X", "-v", "ON_ERROR_STOP=1"],
            cwd=PROJECT_ROOT,
            stdin=-1,
            stdout=-1,
            stderr=-2,
            text=True,
            encoding="utf-8",
        )
        self.assertIn(f"\\ir '{files[0]}'", process.stdin.getvalue())

    @patch("gamedb.load.workflow.steps.subprocess.run")
    def test_archive_step_supplies_its_configured_loader(self, run):
        load_file = PROJECT_ROOT / "load.sql"
        context = WorkflowContext(PROJECT_ROOT)

        ArchiveNamesStep("archives", load_file).execute(context)

        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["--load-file", str(load_file)])

    def test_plan_describes_layers_and_steps(self):
        config = WorkflowConfig.load(PROJECT_ROOT / "pipeline.yml").select(
            layers=("scoring",)
        )

        description = RebuildWorkflow(config).describe()

        self.assertIn("scoring: Apply user preferences", description)
        self.assertIn("build_release_scores (run_sql)", description)
        self.assertIn("020_generate_scores.sql", description)
