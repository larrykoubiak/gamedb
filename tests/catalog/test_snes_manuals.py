from hashlib import sha1
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gamedb.catalog.snes_manuals import INDEX_NAME, _archive_pdf, manual_key, read_manual_index, sync_manuals


PDF = b"%PDF-1.4\n%%EOF\n"
URL = "https://www.nintendo.co.jp/manual.pdf"


class Response(BytesIO):
    status = 200

    def __init__(self, body):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


class SnesManualTests(unittest.TestCase):
    def report(self, root):
        report = root / "report.json"
        manual = {"url": URL, "name": "Game: Manual", "sha1": sha1(PDF).hexdigest()}
        release = {"market": "JP", "manuals": [manual]}
        report.write_text(json.dumps({"games": [{"releases": [release, release]}]}))
        return report

    def test_complete_pdf_is_indexed_once_and_reused(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.report(root)
            with patch("gamedb.catalog.snes_manuals.urlopen", return_value=Response(PDF)) as request:
                result = sync_manuals(report, root, root, workers=1)
                repeated = sync_manuals(report, root, root, workers=1)
            self.assertEqual(result["downloaded"], 1)
            self.assertEqual(repeated["reused"], 1)
            request.assert_called_once()
            (record,) = read_manual_index(root / INDEX_NAME).values()
            self.assertEqual(record["sha1"], sha1(PDF).hexdigest())
            self.assertEqual((root / record["path"]).read_bytes(), PDF)
            self.assertTrue(record["path"].startswith("Japan/Game_ Manual ["))

    def test_invalid_source_does_not_leave_an_indexed_copy(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.report(root)
            with patch("gamedb.catalog.snes_manuals.urlopen", side_effect=lambda *a, **k: Response(b"<html>")), \
                    patch("gamedb.catalog.snes_manuals.sleep"):
                result = sync_manuals(report, root, root, workers=1)
            self.assertIn(URL, result["failures"])
            self.assertNotIn(manual_key(URL), read_manual_index(root / INDEX_NAME))
            self.assertFalse(list(root.glob("Japan/*")))

    def test_archive_selects_the_plain_original_over_ocr_variants(self):
        files = [{"name": name, "source": "original", "sha1": "a" * 40, "size": "42"} for name in (
            "Game - Manual (Searchable).pdf", "Game - Manual (Clearscan).pdf", "Game - Manual.pdf",
        )]
        self.assertEqual(_archive_pdf("manual-item", "Game", files),
                         ("https://archive.org/download/manual-item/Game%20-%20Manual.pdf", "a" * 40, 42))
