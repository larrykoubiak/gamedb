import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
METADATA_SQL = PROJECT_ROOT / "sql/layers/metadata"


class SoftwareMetadataContractTests(unittest.TestCase):
    def test_projection_requires_unambiguous_exact_sha1_identity(self):
        sql = (METADATA_SQL / "020_build.sql").read_text(encoding="utf-8")

        self.assertIn("matched.sha1_hex = entry.sha1_hex", sql)
        self.assertIn(
            "HAVING count(DISTINCT software_release.software_id) = 1", sql
        )

    def test_projection_keeps_conflicts_and_row_level_evidence(self):
        schema = (METADATA_SQL / "010_schema.sql").read_text(encoding="utf-8")
        build = (METADATA_SQL / "020_build.sql").read_text(encoding="utf-8")

        self.assertIn("value_rank bigint NOT NULL", schema)
        self.assertIn("value_count bigint NOT NULL", schema)
        self.assertIn("CREATE TABLE catalog.software_fact_evidence", schema)
        self.assertIn("dense_rank() OVER", build)
        self.assertIn("entry.row_number AS source_row_number", build)
        self.assertIn("entry.sha1_hex AS matched_sha1", build)

    def test_optional_rdb_staging_leaves_an_empty_valid_projection(self):
        schema = (METADATA_SQL / "010_schema.sql").read_text(encoding="utf-8")
        build = (METADATA_SQL / "020_build.sql").read_text(encoding="utf-8")

        self.assertIn("to_regclass('staging.libretro_rdb_entry')", schema)
        self.assertIn("\\gset", schema)
        self.assertTrue(build.lstrip().startswith("\\if :has_libretro_rdb"))
        self.assertTrue(build.rstrip().endswith("\\endif"))


if __name__ == "__main__":
    unittest.main()
