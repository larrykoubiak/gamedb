import csv
import tempfile
import unittest
from pathlib import Path
import zipfile

from gamedb.integrated.importer import IntegratedImporter


class IntegratedImporterTests(unittest.TestCase):
    def test_maintained_undub_manifest_uses_one_modification(self):
        manifest = (
            Path(__file__).resolve().parents[2]
            / "reference" / "integrated_releases.csv"
        )
        with manifest.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertTrue(rows)
        self.assertEqual({row["modification"] for row in rows}, {"undub"})

    def test_manifest_selects_and_names_a_multidisc_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "PS1" / "Example_USA_UNDUB_PS1"
            release.mkdir(parents=True)
            for number in (1, 2):
                with zipfile.ZipFile(release / f"example-disc{number}.zip", "w") as archive:
                    archive.writestr(f"Example Disc {number}.bin", b"rom")
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow((
                    "platform_directory", "release_directory", "title",
                    "manufacturer", "system", "region", "modification",
                    "variant", "zip_pattern",
                ))
                writer.writerow((
                    "PS1", "Example_USA_UNDUB_PS1", "Example", "Sony",
                    "PlayStation", "US", "undub", "", "*.zip",
                ))

            importer = IntegratedImporter(None, root, manifest)
            packages = importer._packages(importer._manifest())

            self.assertEqual(len(packages), 2)
            self.assertEqual(packages[0].media_sequence, 1)
            self.assertEqual(packages[1].media_sequence, 2)
            self.assertEqual(
                packages[0].archive_name,
                "Example (USA) [Undub] [PlayStation] (Disc 1 of 2).zip",
            )

    def test_zip_members_receive_verified_crc_and_sha1(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("folder/game.iso", b"game data")

            rows = IntegratedImporter._members(path)

            self.assertEqual(rows[0]["member_path"], "folder/game.iso")
            self.assertEqual(rows[0]["file_name"], "game.iso")
            self.assertEqual(rows[0]["sha1_hex"], "6f748e7b09ef3868467a25f58fa487df6be96000")
            self.assertTrue(rows[0]["crc_verified"])


if __name__ == "__main__":
    unittest.main()
