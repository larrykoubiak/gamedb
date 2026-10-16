from copy import deepcopy
import unittest

from gamedb.derive.parser.classifier import classify_tags
from gamedb.derive.parser.structure import parse_archive_name


def classify(romset, name):
    parsed = parse_archive_name(romset, name)
    result = classify_tags(romset, name, parsed.tags, parsed.status)
    return parsed, result


class TagClassificationTests(unittest.TestCase):
    def test_no_intro_regions_languages_revision_and_status(self):
        _, result = classify("No-Intro", "Example (USA, Europe) (En,Fr) (Rev A) (Beta 2) (Unl) [b].zip")
        self.assertEqual([t["category"] for t in result.tags], ["region", "language", "revision", "release_status", "license", "dump_status"])
        self.assertEqual(result.tags[0]["details"]["codes"], ["US", "EU"])
        self.assertEqual(result.tags[1]["details"]["codes"], ["en", "fr"])
        self.assertEqual(result.tags[3]["details"], {"code": "beta", "variant": 2})
        self.assertEqual(result.tags[-1]["details"]["code"], "bad_or_hacked")
        self.assertEqual(result.issues, ())

    def test_no_intro_valid_dates_are_release_dates(self):
        for value, precision in (("1994", "year"), ("1994-05", "month"), ("1994-05-03", "day")):
            with self.subTest(value=value):
                _, result = classify("No-Intro", f"Example (USA) ({value}).zip")
                self.assertEqual(result.tags[-1]["category"], "release_date")
                self.assertEqual(result.tags[-1]["details"], {
                    "text": value,
                    "precision": precision,
                    "has_unknown_digits": False,
                })

    def test_no_intro_invalid_calendar_date_stays_unknown(self):
        _, result = classify("No-Intro", "Example (USA) (1994-02-30).zip")
        self.assertEqual(result.tags[-1]["category"], "unknown")

    def test_no_intro_bios_missing_dump_and_unknown_extra_flags(self):
        _, result = classify("No-Intro", "[BIOS] Example (Japan) (NP) (Unexplained) [MIA].zip")
        self.assertEqual([t["category"] for t in result.tags], ["bios", "region", "special", "unknown", "dump_status"])
        self.assertEqual((result.tags[-1]["identifier"], result.tags[-1]["value"]), ("MIA", None))
        self.assertEqual(result.tags[-1]["details"], {"code": "missing"})
        self.assertEqual(result.issues, ("unclassified_tags",))

    def test_publisher_position_wins_over_keyword_matching(self):
        for publisher in ("DE", "en", "PD", "M3", "AGA", "1990", "Moz(IC)art"):
            with self.subTest(publisher=publisher):
                _, result = classify("TOSEC", f"Example (1990)({publisher})(DE)(en).zip")
                self.assertEqual([t["category"] for t in result.tags], ["release_date", "publisher", "region", "language"])
                self.assertEqual(result.tags[1]["details"]["text"], publisher)

    def test_unknown_publisher_is_not_a_literal_publisher_name(self):
        _, result = classify("TOSEC", "Example (19xx)(-).zip")
        self.assertTrue(result.tags[0]["details"]["has_unknown_digits"])
        self.assertEqual(result.tags[1]["details"], {"text": None, "unknown": True})

    def test_partial_dates_keep_precision_and_unknown_digits(self):
        _, result = classify("TOSEC", "Example (19xx-12-2x)(Publisher).zip")
        self.assertEqual(result.tags[0]["details"], {"text": "19xx-12-2x", "precision": "day", "has_unknown_digits": True})

    def test_invalid_calendar_date_does_not_anchor_a_publisher(self):
        for value in ("2001-02-29", "1990-13-10", "1990-12-32"):
            _, result = classify("TOSEC", f"Example ({value})(PD).zip")
            self.assertIn("missing_date_publisher_context", result.issues)
            self.assertTrue(all(tag["category"] == "unknown" for tag in result.tags))

    def test_language_count_does_not_invent_languages(self):
        _, result = classify("TOSEC-ISO", "Example (1990)(Publisher)(EU-US)(M4).zip")
        self.assertEqual(result.tags[-1]["category"], "language")
        self.assertEqual(result.tags[-1]["details"], {"count": 4})

    def test_versions_and_virus_flags_have_different_meanings(self):
        _, result = classify("TOSEC", "Example v1.2 (demo-playable) (1990)(Publisher)(PAL)(proto)[v2 Virus].zip")
        self.assertEqual(result.tags[0]["category"], "version")
        self.assertEqual((result.tags[0]["identifier"], result.tags[0]["value"]), ("v", "1.2"))
        self.assertEqual(result.tags[1]["category"], "demo")
        self.assertEqual(result.tags[-1]["details"], {"code": "virus", "flag": "v", "variant": 2, "detail": "Virus"})
        self.assertEqual((result.tags[-1]["identifier"], result.tags[-1]["value"]), ("v", "Virus"))

    def test_dump_descriptors_preserve_ambiguity_and_variant(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)[cr2 Group][t +3 Trainer][tr fr-partial Someone][a3][b].zip")
        self.assertEqual(result.tags[2]["details"], {"code": "cracked", "flag": "cr", "variant": 2, "detail": "Group"})
        self.assertEqual((result.tags[2]["identifier"], result.tags[2]["value"]), ("cr", "Group"))
        self.assertEqual(result.tags[3]["details"]["detail"], "+3 Trainer")
        self.assertNotIn("variant", result.tags[3]["details"])
        self.assertEqual(result.tags[4]["details"]["detail"], "fr-partial Someone")
        self.assertEqual(result.tags[4]["details"]["language_codes"], ["fr"])
        self.assertEqual(result.tags[4]["details"]["translation_status"], "partial")
        self.assertEqual(result.tags[-1]["details"]["code"], "bad")

    def test_translation_descriptor_exposes_language_and_version(self):
        _, result = classify(
            "TOSEC",
            "Example (1990)(Publisher)(JP)[tr en v1.3 Dejap].zip",
        )
        translation = result.tags[-1]
        self.assertEqual(translation["category"], "dump_modification")
        self.assertEqual(translation["identifier"], "tr")
        self.assertEqual(translation["value"], "en v1.3 Dejap")
        self.assertEqual(
            translation["details"],
            {
                "code": "translated",
                "flag": "tr",
                "detail": "en v1.3 Dejap",
                "language_codes": ["en"],
                "version": "1.3",
            },
        )

    def test_media_part_and_side(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)(Tape 2 of 3 Side B).zip")
        self.assertEqual(result.tags[-1]["details"], {"type": "tape", "part": "2", "total": 3, "side": "B"})
        self.assertEqual((result.tags[-1]["identifier"], result.tags[-1]["value"]), ("Tape", "2"))

    def test_labeled_media_and_unknown_total_are_preserved(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)(Data Disk 2 of y Side B).zip")
        self.assertEqual(result.tags[-1]["details"], {
            "type": "disk", "label": "Data", "part": "2",
            "total_label": "y", "total_unknown": True, "side": "B",
        })

    def test_no_intro_media_is_structured_for_playlist_ordering(self):
        _, result = classify("No-Intro", "Example (USA) (Disk 2 of 3).zip")
        self.assertEqual(result.tags[-1]["category"], "media")
        self.assertEqual(result.tags[-1]["details"], {"type": "disk", "part": "2", "total": 3})

    def test_no_intro_named_system_and_status_tags(self):
        _, result = classify("No-Intro", "Example (USA) (SGB Enhanced) (Promo).zip")
        self.assertEqual(
            [tag["category"] for tag in result.tags],
            ["region", "system_requirement", "release_status"],
        )

    def test_no_intro_alternate_distribution_and_media_label(self):
        _, result = classify("No-Intro", "Example (USA) (Alt 2) (Virtual Console) (Program).zip")
        self.assertEqual(
            [tag["category"] for tag in result.tags],
            ["region", "dump_status", "distribution_channel", "media_label"],
        )
        self.assertEqual(result.tags[1]["details"], {"code": "alternate", "variant": 2})
        self.assertEqual(result.tags[2]["details"], {"code": "virtual_console"})

    def test_tosec_optional_version_after_publisher(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)(v4.0).zip")
        self.assertEqual(result.tags[-1]["category"], "version")
        self.assertEqual((result.tags[-1]["identifier"], result.tags[-1]["value"]), ("v", "4.0"))

    def test_tosec_reference_vocabulary_rules(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)(BY)(TI-83-TI-83+)(Program Disk).zip")
        self.assertEqual(
            [tag["category"] for tag in result.tags],
            ["release_date", "publisher", "region", "system_requirement", "media_label"],
        )

    def test_tosec_license_and_secondary_media_labels(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)(MIT)(Disk 2 of 3)(A)(Game Disk).zip")
        self.assertEqual(
            [tag["category"] for tag in result.tags],
            ["release_date", "publisher", "license", "media", "media_label", "media_label"],
        )
        self.assertEqual(result.tags[3]["details"], {"type": "disk", "part": "2", "total": 3})

    def test_unprefixed_tag_keeps_the_whole_source_value(self):
        _, result = classify("No-Intro", "Example (USA).zip")
        self.assertEqual((result.tags[0]["identifier"], result.tags[0]["value"]), (None, "USA"))

    def test_raw_order_duplicates_and_offsets_are_unchanged(self):
        name = "Example (1990)(Publisher)[a][a][aka Other Title].zip"
        parsed = parse_archive_name("TOSEC", name)
        original = deepcopy(parsed.tags)
        result = classify_tags("TOSEC", name, parsed.tags, parsed.status)
        self.assertEqual(parsed.tags, original)
        self.assertEqual(result.tags[2], result.tags[3])
        self.assertEqual(result.tags[-1]["category"], "additional")
        self.assertEqual(result.tags[-1]["details"], {"text": "aka Other Title"})

    def test_no_implicit_language_or_licensing(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)(JP).zip")
        self.assertEqual([t["category"] for t in result.tags], ["release_date", "publisher", "region"])
        _, result = classify("No-Intro", "Example (Japan).zip")
        self.assertEqual([t["category"] for t in result.tags], ["region"])

    def test_compound_records_are_classified_independently(self):
        parsed = parse_archive_name("TOSEC", "Example (1990)(Publisher) & Other (1991)(Other Publisher).zip")
        self.assertEqual([record.title_candidate for record in parsed.records], ["Example", "Other"])
        for record in parsed.records:
            result = classify_tags("TOSEC", "", record.tags)
            self.assertEqual([tag["category"] for tag in result.tags], ["release_date", "publisher"])
            self.assertEqual(result.issues, ())

    def test_redump_shared_tags_and_media(self):
        _, result = classify("Redump", "Example (USA, Europe) (En,Fr) (Rev A) (Beta 2) (Disc 1 of 2).zip")
        self.assertEqual(
            [tag["category"] for tag in result.tags],
            ["region", "language", "revision", "release_status", "media"],
        )
        self.assertEqual(result.tags[0]["details"], {"codes": ["US", "EU"]})
        self.assertEqual(result.tags[3]["details"], {"code": "beta", "variant": 2})
        self.assertEqual(result.tags[4]["details"], {"type": "disc", "part": "1", "total": 2})
        self.assertEqual(result.issues, ())

    def test_redump_source_specific_media_and_demo_tags(self):
        _, result = classify(
            "Redump",
            "Example (Japan) (2M, 3M) (Game Disc) (Taikenban) (Sega CD 32X).zip",
        )
        self.assertEqual(
            [tag["category"] for tag in result.tags],
            ["region", "media_label", "media_label", "release_status", "system_requirement"],
        )
        self.assertEqual(result.tags[1]["details"], {
            "scheme": "saturn_disc_code", "codes": ["2M", "3M"],
        })
        self.assertEqual(result.tags[2]["details"], {"text": "Game Disc"})
        self.assertEqual(result.tags[3]["details"], {"code": "trial"})
        self.assertEqual(result.issues, ())

    def test_redump_descriptive_preview_and_sample_qualifiers(self):
        cases = (
            ("Square Soft on PlayStation Previews", "preview", "redump.preview_keyword"),
            ("Playable Game Preview", "preview", "redump.preview_keyword"),
            ("Interactive Sampler CD", "sample", "redump.sample_keyword"),
            ("Sample-ban", "sample", "redump.sample_keyword"),
        )
        for qualifier, status, rule in cases:
            with self.subTest(qualifier=qualifier):
                _, result = classify("Redump", f"Example (USA) ({qualifier}).zip")
                self.assertEqual(result.tags[-1]["category"], "release_status")
                self.assertEqual(result.tags[-1]["details"], {"code": status})
                self.assertEqual(result.tags[-1]["rule"], rule)
                self.assertEqual(result.tags[-1]["identifier"], qualifier)
                self.assertEqual(result.issues, ())

    def test_unknown_country_code_is_not_automatically_a_language(self):
        _, result = classify("TOSEC", "Example (1990)(Publisher)(UK)(zz).zip")
        self.assertEqual([t["category"] for t in result.tags[-2:]], ["unknown", "unknown"])
