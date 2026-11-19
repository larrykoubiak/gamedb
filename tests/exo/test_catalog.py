import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from gamedb.catalog.exo import source_facts, work_evidence
from gamedb.exo.editions import platform, scumm_editions
from gamedb.exo.media import open_location


class CatalogEditionsTests(unittest.TestCase):
    def test_launch_choices_keep_specific_platforms_and_distinct_games_in_one_archive(
        self,
    ):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "Mixed.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("Mixed/Original (Windows)/data", b"one")
                archive.writestr("Mixed/Remake/menu.txt", b"")
                archive.writestr("Mixed/Remake/Remake (Macintosh)/platform.txt", b"mac")
                archive.writestr("Mixed/Remake/Remake (Macintosh)/game", b"two")
            items = scumm_editions(
                path, {"mixed": ("one:original", "1"), "remake": ("two:remake", "2")}
            )
            self.assertEqual(
                [(e.environment, e.work_variant) for e in items],
                [("Windows", "one:original"), ("Macintosh", "two:remake")],
            )
            self.assertEqual(items[1].selection, "Remake/Remake (Macintosh)")
            self.assertEqual(items[1].evidence, "platform.txt")
            self.assertEqual(
                platform("", "Mystery (Multi-Platform)")[:2], (None, "Unspecified")
            )

    def test_curator_text_and_aliases_survive_and_ids_alone_cannot_merge_sequels(self):
        fields = {
            "Notes": "First paragraph.\n\n日本語",
            "Genre": "Adventure; Puzzle",
            "Developer": "Trilobyte",
            "ReleaseDate": "1993-01-01",
            "DatabaseID": "13080",
            "Rating": "Mature",
        }
        facts = source_facts(fields, [{"Name": "Guest", "Region": "Working title"}])
        self.assertEqual(facts["description"], ["First paragraph.\n\n日本語"])
        self.assertEqual(facts["genre"], ["Adventure", "Puzzle"])
        self.assertEqual(facts["alternate_title"], ["Guest"])
        self.assertNotEqual(
            work_evidence({"label": "Guest", "fields": fields}, "a"),
            work_evidence({"label": "Guest II", "fields": fields}, "b"),
        )

    def test_archive_access_requires_the_catalogued_member_and_fingerprint(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with ZipFile(root / "extras.zip", "w") as z:
                z.writestr("Guide.pdf", b"first")
                z.writestr("Manual.pdf", b"second")
            with ZipFile(root / "extras.zip") as z:
                crc = z.infolist()[1].CRC
            row = {
                "source_path": "extras.zip",
                "member_no": 2,
                "member_name": "Manual.pdf",
                "size_bytes": 6,
                "crc32": f"{crc:08x}",
            }
            with open_location(root, row) as stream:
                self.assertEqual(stream.read(), b"second")
            for change in (
                {"member_no": 1},
                {"crc32": "00000000"},
                {"source_path": "../extras.zip"},
            ):
                with (
                    self.assertRaises(ValueError),
                    open_location(root, {**row, **change}),
                ):
                    pass


class RelatedMediaHttpTests(unittest.TestCase):
    def test_public_pdf_ranges_and_active_html_downloads(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import Mock

        from gamedb.explorer.related_media import serve

        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content, disposition in (
                ("Guide.pdf", b"%PDF-test", "inline"),
                ("Guide.html", b"<body>archived page", "attachment"),
            ):
                path = root / name
                path.write_bytes(content)
                metadata = {
                    "kind": "extra",
                    "path": name,
                    "revision": "source",
                    "locations": [
                        {
                            "source_path": name,
                            "member_no": 0,
                            "size_bytes": len(content),
                            "mtime_ns": path.stat().st_mtime_ns,
                        }
                    ],
                }
                handler = Mock()
                handler.headers = {"Range": "bytes=0-4"}
                handler.server = SimpleNamespace(exo_root=root, repository=Mock())
                handler.server.repository.exo_asset.return_value = metadata
                handler.wfile = BytesIO()
                serve(handler, "a" * 64)
                handler.send_response.assert_called_once_with(206)
                headers = dict(call.args for call in handler.send_header.call_args_list)
                self.assertTrue(headers["Content-Disposition"].startswith(disposition))
                self.assertEqual(
                    "Content-Security-Policy" in headers, disposition == "attachment"
                )
                self.assertEqual(handler.wfile.getvalue(), content[:5])
