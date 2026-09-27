"""Connection settings must honor explicit overrides and literal secrets."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gamedb.config import load_environment


class EnvironmentTests(unittest.TestCase):
    def test_file_defaults_preserve_explicit_environment_and_literal_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("PGHOST=file-host\nPGPORT=1234\nPGPASSWORD='test ${USER} # literal'\n")
            with patch.dict(os.environ, {"PGHOST": "override-host", "USER": "expanded"}, clear=True):
                load_environment(path)
                self.assertEqual(os.environ["PGHOST"], "override-host")
                self.assertEqual(os.environ["PGPORT"], "1234")
                self.assertEqual(os.environ["PGPASSWORD"], "test ${USER} # literal")

    def test_cli_loads_repository_file_before_connecting(self):
        from gamedb.cli import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("PGHOST=fixture-host\n")
            with patch.dict(os.environ, {}, clear=True), patch("gamedb.config.ENV_FILE", path):
                def fake_parse(**kwargs):
                    self.assertEqual(os.environ["PGHOST"], "fixture-host")
                    return {"processed": 0}

                with patch("gamedb.romvault.importer.parse_archive_names", side_effect=fake_parse):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["parse-names"]), 0)

    def test_missing_file_keeps_process_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PGHOST": "environment-only"}, clear=True):
                load_environment(Path(directory) / "missing.env")
                self.assertEqual(dict(os.environ), {"PGHOST": "environment-only"})
