from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gamedb.catalog.media import (
    MediaCatalogBuilder,
    ThumbnailPathIndex,
    region_compatibility,
)


class MediaSelectionTests(unittest.TestCase):
    def test_regions_are_strong_match_evidence(self):
        self.assertEqual(
            region_compatibility(frozenset({"USA"}), frozenset({"USA"})),
            ("exact", 5),
        )
        self.assertEqual(
            region_compatibility(frozenset({"WORLD"}), frozenset({"USA"})),
            ("world", 4),
        )
        self.assertEqual(
            region_compatibility(frozenset({"JAPAN"}), frozenset({"USA"})),
            ("mismatch", 0),
        )

    def test_missing_region_is_unknown_not_a_mismatch(self):
        self.assertEqual(
            region_compatibility(frozenset(), frozenset({"USA"})),
            ("unknown", 1),
        )

    def test_empty_source_does_not_replace_the_existing_projection(self):
        builder = MediaCatalogBuilder(
            MagicMock(), Path("."), Path("/missing"), Path("/missing-index")
        )
        with (
            patch.object(builder, "_load_mapping", return_value=({}, {})),
            patch.object(builder, "_load_images", return_value={}),
            patch.object(builder, "_replace_projection") as replace,
            self.assertRaisesRegex(RuntimeError, "No mapped Libretro"),
        ):
            builder.execute()

        replace.assert_not_called()

    def test_mapping_rejects_duplicate_canonical_systems(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            reference.mkdir()
            (reference / "libretro_thumbnail_systems.csv").write_text(
                "canonical_manufacturer_name,canonical_system_name,"
                "libretro_directory\n"
                "Nintendo,NES,Nintendo - NES\n"
                "Nintendo,NES,Nintendo - Famicom\n",
                encoding="utf-8",
            )
            builder = MediaCatalogBuilder(
                MagicMock(), root, Path("/missing"), Path("/missing-index")
            )

            with self.assertRaisesRegex(ValueError, "Duplicate canonical system"):
                builder._load_mapping()

    def test_path_index_falls_back_to_filesystem_without_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "thumbnails"
            image = root / "Nintendo - NES/Named_Boxarts/A Game.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"png")
            git_directory = root / ".git"
            git_directory.mkdir()
            (git_directory / "HEAD").write_text("a" * 40 + "\n", encoding="ascii")
            cache = Path(directory) / "cache/paths.gz"

            with patch("gamedb.catalog.media.shutil.which", return_value=None):
                paths = list(ThumbnailPathIndex(root, cache).paths())

            self.assertEqual(
                paths, ["Nintendo - NES/Named_Boxarts/A Game.png"]
            )
            self.assertTrue(cache.is_file())


if __name__ == "__main__":
    unittest.main()
