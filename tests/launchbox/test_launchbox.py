import io
from pathlib import Path
import tempfile
import unittest
from xml.etree.ElementTree import ParseError

from gamedb.launchbox.importer import records
from gamedb.launchbox.matching import match_candidates, read_platform_map, title_key, resolve_candidates


class ReaderTests(unittest.TestCase):
    def test_preserves_unicode_empty_fields_and_source_row_positions(self):
        xml = '''<LaunchBox><Game><DatabaseID>12</DatabaseID><Name>Pokémon &amp; Co.</Name>
            <Overview>First\nsecond</Overview><Genres /></Game>
            <GameImage><DatabaseID>12</DatabaseID></GameImage>
            <GameAlternateName><DatabaseID>12</DatabaseID><AlternateName>Other</AlternateName>
            </GameAlternateName></LaunchBox>'''
        rows = list(records(io.StringIO(xml)))
        self.assertEqual(rows[0][2]["Name"], "Pokémon & Co.")
        self.assertEqual(rows[0][2]["Overview"], "First\nsecond")
        self.assertEqual(rows[0][2]["Genres"], "")
        self.assertIn("&amp;", rows[0][3])
        self.assertEqual(rows[1][1], "GameImage")
        self.assertIsNone(rows[1][3])
        self.assertEqual(rows[2][0], 3)

    def test_rejects_wrong_root_and_truncated_document(self):
        with self.assertRaises(ValueError):
            list(records(io.StringIO('<Unexpected/>')))
        with self.assertRaises(ParseError):
            list(records(io.StringIO('<LaunchBox><Game>')))


class MatchingTests(unittest.TestCase):
    def software(self, ident, *titles, system="NES"):
        return dict(id=ident, manufacturer_name="Nintendo", system_name=system, titles=set(titles))

    def game(self, name, platform="Nintendo NES"):
        return dict(Name=name, Platform=platform)

    def match(self, software, games, aliases=None):
        return match_candidates(software, games, aliases or {}, {("Nintendo", "NES"): {"Nintendo NES"}})

    def test_normalization_handles_articles_and_unicode_but_keeps_editions(self):
        self.assertEqual(title_key("Legend, The"), title_key("The Legend"))
        self.assertEqual(title_key("Ｐｏｋéｍｏｎ"), title_key("Pokémon"))
        self.assertNotEqual(title_key("Pokemon"), title_key("Pokémon"))
        self.assertNotEqual(title_key("Game II"), title_key("Game 2"))
        self.assertNotEqual(title_key("Game (Prototype)"), title_key("Game"))
        self.assertNotEqual(title_key("Game: Deluxe"), title_key("Game"))

    def test_alias_matching_is_platform_scoped_and_deduplicated(self):
        results = self.match([self.software(1, "Regional Name")], {
            10: self.game("Original"), 11: self.game("Regional Name", "Nintendo SNES")
        }, {10: ["Regional Name", "Regional Name"]})
        self.assertEqual(results[0]["status"], "unique")
        self.assertEqual(results[0]["database_ids"], [10])
        self.assertEqual(results[0]["selected_database_id"], 10)

    def test_duplicate_source_titles_are_ambiguous(self):
        result = self.match([self.software(1, "Game")], {10: self.game("Game"), 11: self.game("Game")})
        self.assertEqual(result[0]["status"], "ambiguous_source")

    def test_duplicate_catalog_titles_cannot_both_claim_one_game(self):
        result = self.match([self.software(1, "Game"), self.software(2, "Game")], {10: self.game("Game")})
        self.assertEqual([r["status"] for r in result], ["ambiguous_catalog"] * 2)

    def test_ambiguous_claimant_also_blocks_apparently_unique_claimant(self):
        result = self.match([self.software(1, "Game"), self.software(2, "Game", "Other")],
                            {10: self.game("Game"), 11: self.game("Other")})
        self.assertEqual([r["status"] for r in result], ["ambiguous_catalog", "ambiguous_source"])

    def test_unmapped_platform_and_unmatched_title_remain_distinct(self):
        result = self.match([self.software(1, "Game", system="SNES"), self.software(2, "Other")], {10: self.game("Game")})
        self.assertEqual([r["status"] for r in result], ["unmapped_platform", "unmatched"])

    def test_empty_normalized_names_do_not_match(self):
        result = self.match([self.software(1, "!!!")], {10: self.game("???")})
        self.assertEqual(result[0]["status"], "unmatched")

    def test_platform_map_supports_explicit_multiple_platforms(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.csv"
            path.write_text("canonical_manufacturer_name,canonical_system_name,launchbox_platform\nNintendo,NES,NES\nNintendo,NES,Famicom\n")
            self.assertEqual(read_platform_map(path), {("Nintendo", "NES"): {"NES", "Famicom"}})


class DisambiguationTests(unittest.TestCase):
    def item(self, **facts):
        return dict(id=1, manufacturer_name="Nintendo", system_name="NES",
                    titles={"Game"}, match_facts=facts)

    def game(self, name="Game", **fields):
        return dict(Name=name, Platform="Nintendo NES", **fields)

    def test_title_alone_does_not_resolve(self):
        self.assertEqual(resolve_candidates(self.item(), {10}, {10: self.game()}), (None, []))

    def test_literal_title_and_year_can_resolve_a_shared_metadata_link(self):
        items = [self.item(release_date={"1995"}), self.item(release_date={"1995"})]
        items[1]["id"] = 2
        result = match_candidates(items, {10: self.game(ReleaseYear="1995")}, {},
                                  {("Nintendo", "NES"): {"Nintendo NES"}})
        self.assertEqual([r["status"] for r in result], ["resolved_shared"] * 2)
        self.assertEqual([r["selected_database_id"] for r in result], [10, 10])
        self.assertEqual([r["software_id"] for r in result], [1, 2])

    def test_sequel_alias_does_not_override_corroborated_primary_title(self):
        games = {10: self.game(ReleaseYear="1995"), 11: self.game("Game 2", ReleaseYear="1996")}
        selected, evidence = resolve_candidates(self.item(release_date={"1995"}), {10, 11}, games)
        self.assertEqual(selected, 10)
        self.assertIn("release_year", evidence)

    def test_same_name_same_year_remains_ambiguous(self):
        games = {10: self.game(ReleaseYear="1995"), 11: self.game(ReleaseYear="1995")}
        self.assertIsNone(resolve_candidates(self.item(release_date={"1995"}), {10, 11}, games)[0])

    def test_company_conflict_blocks_year_only_resolution(self):
        game = self.game(ReleaseYear="1995", Publisher="Different studio")
        self.assertIsNone(resolve_candidates(self.item(release_date={"1995"}, publisher={"Studio"}), {10}, {10: game})[0])

    def test_year_conflict_blocks_company_only_resolution(self):
        game = self.game(ReleaseYear="1996", Publisher="Studio")
        self.assertIsNone(resolve_candidates(self.item(release_date={"1995"}, publisher={"Studio"}), {10}, {10: game})[0])

    def test_punctuation_collision_requires_two_corroborating_fields(self):
        game = self.game("Game +", ReleaseYear="1995")
        self.assertIsNone(resolve_candidates(self.item(release_date={"1995"}), {10}, {10: game})[0])

    def test_conflicting_catalog_dates_do_not_supply_date_support(self):
        game = self.game(ReleaseYear="1995")
        self.assertIsNone(resolve_candidates(self.item(release_date={"1995", "1996"}), {10}, {10: game})[0])


if __name__ == "__main__":
    unittest.main()
