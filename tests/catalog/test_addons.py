import json
import unittest

from gamedb.catalog.addons import ADDONS, DISC_ADDONS, _addon_catalog, _merge_games
from gamedb.config import PROJECT_ROOT


class AddonTests(unittest.TestCase):
    def test_fds_preserves_cartridge_identity_and_separates_the_lost_levels(self):
        reference = json.loads((PROJECT_ROOT / "reference/fds_retail.json").read_text(encoding="utf-8"))
        titles = {"Super Mario Bros. 2", "Yume Kōjō: Doki Doki Panic"}
        reference["titles"] = [row for row in reference["titles"] if row["title"] in titles]
        addon, _, parents = _addon_catalog(ADDONS["nes"], reference)
        cartridge = {"key": "cart-release", "market": "JP"}
        base = {"games": [{"key": "base-game", "title": "Super Mario Bros. 2", "aliases": [], "releases": [cartridge]}]}
        _merge_games(base, addon, parents)

        shared, lost_levels = base["games"]
        self.assertEqual(shared["key"], "base-game")
        self.assertIs(shared["releases"][0], cartridge)
        self.assertEqual(shared["releases"][1]["titles"], ["Yume Kōjō: Doki Doki Panic"])
        self.assertEqual(shared["releases"][1]["hardware"], "fds")
        self.assertEqual(lost_levels["title"], "Super Mario Bros.: The Lost Levels")
        self.assertEqual(lost_levels["releases"][0]["titles"], ["Super Mario Bros. 2"])
        self.assertEqual(lost_levels["releases"][0]["channel"], "disk")

    def test_separately_released_fds_parts_share_a_game(self):
        reference = json.loads((PROJECT_ROOT / "reference/fds_retail.json").read_text(encoding="utf-8"))
        reference["titles"] = [row for row in reference["titles"]
                               if row.get("gameTitle") == "Famicom Mukashibanashi: Shin Onigashima"]
        addon, _, _ = _addon_catalog(ADDONS["nes"], reference)
        (game,) = addon["games"]
        self.assertEqual(len(game["releases"]), 2)
        self.assertEqual(len({release["key"] for release in game["releases"]}), 2)
        self.assertTrue(all(release["market"] == "JP" for release in game["releases"]))

    def test_32x_cd_releases_share_a_game_with_the_standard_cd_edition(self):
        reference = json.loads((PROJECT_ROOT / "reference/segacd_retail.json").read_text(encoding="utf-8"))
        reference["titles"] = [row for row in reference["titles"]
                               if row.get("gameTitle", row["title"]) == "Night Trap"]
        addon, _, _ = _addon_catalog(DISC_ADDONS["megadrive"], reference)
        (game,) = addon["games"]
        normal = next(release for release in game["releases"] if release["hardware"] == "segacd")
        hybrid = next(release for release in game["releases"] if release["hardware"] == "32x-cd")
        self.assertNotEqual(normal["key"], hybrid["key"])
        self.assertEqual(normal["channel"], "optical-disc")
        self.assertEqual(hybrid["requiredHardware"], ["segacd", "32x"])
