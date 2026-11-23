import json
from types import SimpleNamespace
import unittest

from gamedb.catalog.cartridges import _jensma_rows, _markets_in_serial, mame_cartridges
from gamedb.catalog.retail_media import _launchbox_art, _libretro_art, _manual_link_regions, add_manuals
from gamedb.catalog.references import KIRKLAND_ITEM, SourceIndex
from gamedb.catalog.retail_source import known_credit


def release(edition, market):
    return {"key": market, "edition": edition, "market": market, "titles": [edition],
            "channel": "cartridge", "status": "matched"}


class SnesEnrichmentTests(unittest.TestCase):
    def test_cartridge_product_code_is_not_a_market_suffix(self):
        self.assertEqual(_markets_in_serial("SHVC-NA"), "JP")
        self.assertEqual(_markets_in_serial("SHVC-UK"), "JP")
        self.assertEqual(_markets_in_serial("SNSP-RI-UKV"), "PAL")

    def test_mame_uses_the_program_rom_and_keeps_the_cartridge_market(self):
        entries = b"""
          <softwarelist>
            <software name="game">
              <description>Game (Japan, rev. A)</description>
              <info name="serial" value="SHVC-NA"/>
              <part><feature name="pcb" value="SHVC-1A0N-20"/>
                <dataarea name="rom"><rom sha1="program"/></dataarea>
                <dataarea name="addon"><rom sha1="coprocessor"/></dataarea>
              </part>
            </software>
            <software name="other">
              <description>Other Game (USA)</description>
              <part><dataarea name="rom"><rom sha1="part-1"/><rom sha1="part-2"/></dataarea></part>
            </software>
          </softwarelist>
        """
        (digest, markets, claim), = mame_cartridges(entries, "snes.xml")
        self.assertEqual((digest, markets), ("program", {"JP"}))
        self.assertEqual(claim["serials"], ["SHVC-NA"])
        self.assertEqual(claim["boards"], ["SHVC-1A0N-20"])

    def test_board_observations_require_an_unambiguous_market(self):
        index = b"""
          <table>
            <tr><td>Game</td><td>SHVC-G1 (JPN)</td><td>2 MB</td><td>64 KB</td><td>SHVC-1A0N-20</td></tr>
            <tr><td>Game</td><td>SHVC-G1, SNS-G1-USA</td><td>2 MB</td><td>64 KB</td><td>SHVC-1A0N-20</td></tr>
            <tr><td>Other</td><td>SNS-7777-USA</td><td>2 MB</td><td>64 KB</td><td>UNKNOWN</td></tr>
          </table>
        """
        (name, market, serial, claim), = _jensma_rows(index)
        self.assertEqual((name, market, serial), ("Game", "JP", "SHVC-G1"))
        self.assertEqual(claim["boards"], ["SHVC-1A0N-20"])

    def test_a_shared_rom_does_not_prove_a_regions_box_art(self):
        archive_name = "Game (Japan, USA).zip"
        japan = release("Game", "JP")
        north_america = release("Game", "NA")
        for entry in (japan, north_america):
            entry["archives"] = [{"archiveNames": [archive_name], "regions": ["JP", "US"],
                                  "revisions": [], "versions": []}]
        paths = {"snes": {"Named_Boxarts/Game (Japan, USA).png", "Named_Titles/Game (Japan, USA).png"}}
        self.assertEqual([kind for _, kind, _ in _libretro_art(japan, paths)], ["title"])
        reviewed = {(archive_name, "boxart"): {"market": "NA", "regions": ["US"], "source": {"name": "Box scan"}}}
        self.assertEqual([kind for _, kind, _ in _libretro_art(japan, paths, reviewed)], ["title"])
        boxart, title = [asset for _, _, asset in _libretro_art(north_america, paths, reviewed)]
        self.assertEqual(boxart["basis"], "reviewed-image")
        self.assertEqual(boxart["regions"], ["US"])
        self.assertEqual(title["basis"], "shared-rom")

    def test_shared_rom_can_supply_gameplay_but_logo_must_match_the_local_title(self):
        japan = release("Japanese Title", "JP")
        archive = {"archiveNames": ["Game (Japan, USA).zip"], "regions": ["JP", "US"],
                   "title": "Western Title", "revisions": [], "versions": []}
        japan["archives"] = [archive]
        paths = {"snes": {"Named_Snaps/Game (Japan, USA).png", "Named_Logos/Game (Japan, USA).png"}}
        self.assertEqual([kind for _, kind, _ in _libretro_art(japan, paths)], ["snap"])
        archive["title"] = "Japanese Title"
        self.assertEqual([kind for _, kind, _ in _libretro_art(japan, paths)], ["snap", "logo"])

    def test_launchbox_unmarked_logo_is_a_fallback_for_its_named_release(self):
        image = SimpleNamespace(image_type="Clear Logo", region="", file_name="image.png", crc32=0)
        images = {1: [(image, "Western Title")]}
        self.assertFalse(list(_launchbox_art(release("Japanese Title", "JP"), [1], images)))
        (rank, kind, asset), = _launchbox_art(release("Western Title", "NA"), [1], images)
        self.assertEqual((rank, kind, asset["basis"]), (-1, "logo", "source-title"))

    def test_manuals_require_market_evidence_and_only_original_pdfs(self):
        japan = release("Game", "JP")
        north_america = release("Game", "NA")
        europe = release("Game", "PAL")
        catalog = {"games": [{"releases": [japan, north_america, europe]}]}
        snapshot = SourceIndex("https://example.com", json.dumps({
            "metadata": {"identifier": KIRKLAND_ITEM},
            "files": [
                {"name": "Game (USA).pdf", "source": "original"},
                {"name": "Game (Europe).pdf", "source": "derivative"},
                {"name": "Game (Japan, USA).pdf", "source": "original"},
                {"name": "Game (Japan) (Fan Manual).pdf", "source": "original"},
            ],
        }).encode())
        add_manuals(catalog, {"kirkland-archive.json": snapshot})
        self.assertEqual([manual["name"] for manual in north_america["manuals"]], ["Game (USA)"])
        self.assertNotIn("manuals", japan)
        self.assertNotIn("manuals", europe)

    def test_region_suffix_is_distinct_from_a_country_in_the_manual_title(self):
        self.assertEqual(_manual_link_regions("/details/world-cup-usa-94-pal/mode/2up"), ["PAL"])
        self.assertEqual(_manual_link_regions("/details/world-cup-usa-94"), [])
        self.assertEqual(_manual_link_regions("/download/item/Game%20(SNSP-AJ3P-UKV).pdf"), ["UKV"])

    def test_uncertain_company_names_are_omitted_from_credits(self):
        self.assertFalse(known_credit("Nintendo ???"))
        self.assertFalse(known_credit("Unknown developer"))
        self.assertTrue(known_credit("Nintendo R&D1"))
