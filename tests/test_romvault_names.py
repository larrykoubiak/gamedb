import unittest

from gamedb.romvault.names import parse_archive_name


class ArchiveNameTests(unittest.TestCase):
    def test_tosec_bare_suffix_and_unqualified_groups(self):
        result = parse_archive_name("TOSEC-ISO", "4 Wheel Thunder v1.002 (2000)(Midway)(US)[!].zip")
        self.assertEqual(result.title_candidate, "4 Wheel Thunder")
        self.assertEqual([t["value"] for t in result.tags], ["v1.002", "2000", "Midway", "US", "!"])
        self.assertEqual([t["delimiter"] for t in result.tags], ["", "()", "()", "()", "[]"])
        self.assertEqual(result.status, "parsed")

    def test_source_specific_bare_suffix(self):
        for romset in ("No-Intro", "Redump"):
            result = parse_archive_name(romset, "Reach for the Stars v2.0 (USA, Europe).zip")
            self.assertEqual(result.title_candidate, "Reach for the Stars v2.0")
            self.assertEqual([t["value"] for t in result.tags], ["USA, Europe"])

    def test_parentheses_inside_title_are_preserved(self):
        title = "Hiraki Kazuo Sensei (Tokyo Daigaku) Kanshuu - Suku Suku Kosodate DS - Akachan to Asobou!"
        result = parse_archive_name("No-Intro", title + " (Japan).zip")
        self.assertEqual(result.title_candidate, title)
        self.assertEqual([t["value"] for t in result.tags], ["Japan"])
        self.assertEqual(result.status, "review")

    def test_nested_parentheses_remain_one_tag(self):
        result = parse_archive_name("TOSEC", "Depressed (1989)(Moz(IC)art)[a].zip")
        self.assertEqual(result.title_candidate, "Depressed")
        self.assertEqual([t["value"] for t in result.tags], ["1989", "Moz(IC)art", "a"])
        self.assertEqual(result.status, "parsed")

    def test_tosec_title_may_itself_be_parenthetical(self):
        result = parse_archive_name("TOSEC", "(Bah!) (1988-06-07)(2000 Volt)[a].zip")
        self.assertEqual(result.title_candidate, "(Bah!)")
        self.assertEqual([t["value"] for t in result.tags], ["1988-06-07", "2000 Volt", "a"])

    def test_leading_tags_keep_their_order(self):
        result = parse_archive_name("No-Intro", "[BIOS] 32X M68000 (USA).zip")
        self.assertEqual(result.title_candidate, "32X M68000")
        self.assertEqual([t["value"] for t in result.tags], ["BIOS", "USA"])
        self.assertEqual(result.status, "parsed")

    def test_qualifiers_are_not_split_or_deduplicated(self):
        result = parse_archive_name("TOSEC", "Game (1990)(Author)(en-fr)[a][a][aka Other Title].zip")
        self.assertEqual([t["value"] for t in result.tags], ["1990", "Author", "en-fr", "a", "a", "aka Other Title"])

    def test_lexical_details_can_be_reconstructed(self):
        name = "Été v1.2 (demo) (19xx)( Auteur )[unknown [nested]].ZIP"
        result = parse_archive_name("TOSEC", name)
        self.assertEqual(result.title_candidate, "Été")
        self.assertEqual(result.extension, ".ZIP")
        for tag in result.tags:
            raw = tag["value"]
            if tag["delimiter"]:
                raw = tag["delimiter"][0] + raw + tag["delimiter"][1]
            self.assertEqual(name[tag["start"]:tag["end"]], raw)

    def test_malformed_input_is_retained_for_review(self):
        for name in ("Game (1990)(Broken].zip", "Game (1990)((Broken)(PD).zip", "Odekake Lester - Lelele no Le (^^; (Japan).zip"):
            result = parse_archive_name("TOSEC", name)
            self.assertEqual(result.status, "review")
            self.assertIn("unbalanced_delimiters", result.issues)
            self.assertTrue(result.title_candidate)

    def test_text_between_groups_is_not_silently_discarded(self):
        result = parse_archive_name("No-Intro", "First Game (Demo) + Second Game (Europe).zip")
        self.assertEqual(result.title_candidate, "First Game (Demo) + Second Game")
        self.assertEqual([t["value"] for t in result.tags], ["Europe"])
        self.assertEqual(result.status, "review")

    def test_unknown_extension_is_not_removed(self):
        result = parse_archive_name("TOSEC", "Example v1.2")
        self.assertEqual(result.title_candidate, "Example v1.2")
        self.assertIn("missing_zip_extension", result.issues)

    def test_legacy_unknown_name(self):
        result = parse_archive_name("TOSEC", "ZZZ-UNK-10.zip")
        self.assertEqual(result.title_candidate, "ZZZ-UNK-10")
        self.assertIn("legacy_unknown_name", result.issues)

    def test_empty_title_and_tag(self):
        result = parse_archive_name("Redump", "(USA)[].zip")
        self.assertIn("empty_title", result.issues)
        self.assertIn("empty_tag", result.issues)


if __name__ == "__main__":
    unittest.main()
