import unittest

from gamedb.explorer.snes_metadata import add_release_metadata


class SnesMetadataTests(unittest.TestCase):
    def test_peripherals_follow_the_verified_release_checksum(self):
        north_america, japan, pal = ({"key": key} for key in ("na", "jp", "pal"))
        game = {"releases": [north_america, japan, pal]}
        add_release_metadata(game, {
            "na": {"genres": ["Puzzle"], "players": ["1"], "crc32s": ["0944a5c3"]},
            "jp": {"genres": ["Puzzle"], "players": ["1", "2"], "crc32s": ["00000000"]},
        })
        self.assertEqual(north_america["metadata"], {"genres": ["Puzzle"], "players": 1, "peripherals": ["mouse"]})
        self.assertEqual(japan["metadata"], {"genres": ["Puzzle"]})
        self.assertNotIn("metadata", pal)
