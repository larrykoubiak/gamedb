import unittest

from gamedb.derive.parser.structure import (
    parse_archive_name, should_ignore_archive_name,
)


class ArchiveNameTests(unittest.TestCase):
    def test_maybe_intro_uses_no_intro_structure_and_ignores_docs(self):
        parsed = parse_archive_name(
            "English Translations",
            "Bahamut Lagoon (Japan) [T-En by DeJap v1.3].zip",
        )

        self.assertEqual(parsed.title_candidate, "Bahamut Lagoon")
        self.assertEqual(
            [tag["value"] for tag in parsed.tags],
            ["Japan", "T-En by DeJap v1.3"],
        )
        self.assertTrue(
            should_ignore_archive_name(
                "English Translations", "_Nintendo Super Famicom [T-En] Docs.zip"
            )
        )

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
        self.assertEqual(result.status, "parsed")

    def test_title_ending_in_parentheses_uses_region_as_boundary(self):
        title = "Kanaderu Score (5-7) + Yusuke Akamatsu Theater (5-7)"
        result = parse_archive_name("No-Intro", title + " (Japan).zip")
        self.assertEqual(result.title_candidate, title)
        self.assertEqual([tag["value"] for tag in result.tags], ["Japan"])

    def test_tosec_compound_archive_has_independent_records(self):
        result = parse_archive_name(
            "TOSEC",
            "First Game (1988)(One & Two) & Second Game v1.2 (1990)(Other)[a].zip",
        )
        self.assertEqual([record.title_candidate for record in result.records], ["First Game", "Second Game"])
        self.assertEqual(
            [[tag["value"] for tag in record.tags] for record in result.records],
            [["1988", "One & Two"], ["v1.2", "1990", "Other", "a"]],
        )
        self.assertEqual(result.status, "parsed")

    def test_ampersand_in_one_title_does_not_create_records(self):
        result = parse_archive_name("TOSEC", "Dungeons & Dragons (1990)(Publisher).zip")
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.title_candidate, "Dungeons & Dragons")

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
        for name in ("Game (1990)(Broken].zip", "Game (1990)((Broken)(PD).zip"):
            result = parse_archive_name("TOSEC", name)
            self.assertEqual(result.status, "review")
            self.assertIn("unbalanced_delimiters", result.issues)
            self.assertTrue(result.title_candidate)

    def test_suffix_is_recovered_after_malformed_title_delimiter(self):
        result = parse_archive_name("TOSEC", "AppleWriter ][ (1981)(Apple)(II+).zip")
        self.assertEqual(result.title_candidate, "AppleWriter ][")
        self.assertEqual([tag["value"] for tag in result.tags], ["1981", "Apple", "II+"])
        self.assertEqual(result.status, "parsed")

    def test_unclosed_parenthesis_before_region_is_title_text(self):
        result = parse_archive_name(
            "No-Intro", "Odekake Lester - Lelele no Le (^^; (Japan).zip"
        )
        self.assertEqual(result.title_candidate, "Odekake Lester - Lelele no Le (^^;")
        self.assertEqual([tag["value"] for tag in result.tags], ["Japan"])
        self.assertEqual(result.status, "parsed")

    def test_parenthesized_text_before_region_remains_in_title(self):
        result = parse_archive_name("No-Intro", "First Game (Demo) + Second Game (Europe).zip")
        self.assertEqual(result.title_candidate, "First Game (Demo) + Second Game")
        self.assertEqual([t["value"] for t in result.tags], ["Europe"])
        self.assertEqual(result.status, "parsed")

    def test_unknown_extension_is_not_removed(self):
        result = parse_archive_name("TOSEC", "Example v1.2")
        self.assertEqual(result.title_candidate, "Example v1.2")
        self.assertIn("missing_zip_extension", result.issues)

    def test_legacy_unknown_name(self):
        self.assertTrue(should_ignore_archive_name("TOSEC", "ZZZ-UNK-10.zip"))
        self.assertTrue(should_ignore_archive_name("TOSEC-ISO", "ZZZ-UNK-10.zip"))
        self.assertFalse(should_ignore_archive_name("No-Intro", "ZZZ-UNK-10.zip"))

    def test_empty_title_and_tag(self):
        result = parse_archive_name("Redump", "(USA)[].zip")
        self.assertIn("empty_title", result.issues)
        self.assertIn("empty_tag", result.issues)


if __name__ == "__main__":
    unittest.main()
