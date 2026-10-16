import csv
from pathlib import Path
import tempfile
import unittest

from gamedb.history.importer import artifact_row, match_review_rows


class HistoricalImporterTests(unittest.TestCase):
    def test_match_review_preserves_positive_negative_and_unreviewed_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matches.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow((
                    "System", "softwareName", "normalizedSoftwareName",
                    "normalizedReleaseName", "matchMethod", "matchScore",
                    "URL", "NewScore",
                ))
                writer.writerow(("NES", "Q-bert", "Qbert", "Q*bert", "QRatio", 91, "", 100))
                writer.writerow(("GB", "Frogger 2", "Frogger 2", "Frogger", "QRatio", 100, "", 0))
                writer.writerow(("SNES", "Mario", "Mario", "Mario", "QRatio", 100, "", 100))

            rows = list(match_review_rows(path))

        self.assertEqual(
            [row["review_decision"] for row in rows],
            ["accepted", "rejected", "unreviewed"],
        )

    def test_artifact_row_records_content_hash_without_reading_metadata_as_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.dat"
            path.write_bytes(b"historical source")

            row = artifact_row("snapshot", "artifact", "DAT", path)

        self.assertEqual(row["size_bytes"], 17)
        self.assertEqual(
            row["sha256"],
            "5c8b314eb484fbe4ea676eb00e4fddc7faf21fc9d7602398bd01ce189b1d2c82",
        )


if __name__ == "__main__":
    unittest.main()
