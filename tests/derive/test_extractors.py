import unittest

from gamedb.derive.extractors.archive_name_extract import ArchiveNameExtractor
from gamedb.derive.extractors.dat_extract import DatExtractor
from gamedb.derive.extractors.translation_member_title_extract import (
    TranslationMemberTitleExtractor,
)


class ArchiveNameExtractorTests(unittest.TestCase):
    def test_integrated_undub_has_typed_platform_and_media(self):
        result = ArchiveNameExtractor().extract(
            "Integrated",
            "Grandia (USA) [Undub] [PlayStation] (Disc 1 of 2).zip",
        )

        record = result.records[0]
        assertions = {(item.key, item.value) for item in record.assertions}

        self.assertEqual(record.title, "Grandia")
        self.assertIn(("region", "US"), assertions)
        self.assertIn(("dump_modification", "undub"), assertions)
        self.assertIn(("system_requirement", "PlayStation"), assertions)
        self.assertEqual(record.media_parts[0].sequence, 1)
        self.assertEqual(record.media_parts[0].total, 2)

    def test_maybe_intro_translation_is_typed_for_scoring(self):
        result = ArchiveNameExtractor().extract(
            "English Translations",
            "Bahamut Lagoon (Japan) "
            "[T-En by DeJap+Neill Corlett+Tomato v1.3].zip",
        )

        record = result.records[0]
        assertions = {(item.key, item.value) for item in record.assertions}

        self.assertEqual(record.title, "Bahamut Lagoon")
        self.assertIn(("region", "JP"), assertions)
        self.assertIn(("language", "en"), assertions)
        self.assertIn(("version", "1.3"), assertions)
        self.assertIn(("dump_modification", "translated"), assertions)

    def test_maybe_intro_incomplete_and_localized_title_flags_are_retained(self):
        result = ArchiveNameExtractor().extract(
            "English Translations",
            "Example (Japan) [T-En by Group v0.9] [i] [n].zip",
        )

        assertions = {
            (item.key, item.value) for item in result.records[0].assertions
        }

        self.assertIn(("release_status", "incomplete_translation"), assertions)
        self.assertIn(("special", "localized_title"), assertions)

    def test_maybe_intro_variant_hack_is_explicit(self):
        result = ArchiveNameExtractor().extract(
            "English Translations",
            "Bahamut Lagoon (Japan) [T-En by DeJap v1.3] "
            "(Emulation Hack).zip",
        )

        assertions = {
            (item.key, item.value) for item in result.records[0].assertions
        }

        self.assertIn(("dump_modification", "translated"), assertions)
        self.assertIn(("dump_modification", "hacked"), assertions)

    def test_translation_is_emitted_as_typed_assertions(self):
        result = ArchiveNameExtractor().extract(
            "TOSEC",
            "Bahamut Lagoon (1996)(Squaresoft)(JP)[tr en v1.3 Dejap].zip",
        )

        record = result.records[0]
        assertions = {(item.key, item.value) for item in record.assertions}

        self.assertEqual(record.title, "Bahamut Lagoon")
        self.assertIn(("region", "JP"), assertions)
        self.assertIn(("language", "en"), assertions)
        self.assertIn(("version", "1.3"), assertions)
        self.assertIn(("dump_modification", "translated"), assertions)
        self.assertEqual(record.tags[-1].raw_value, "tr en v1.3 Dejap")
        self.assertEqual(len(record.grouping_signature), 64)

    def test_media_is_typed_before_database_loading(self):
        result = ArchiveNameExtractor().extract(
            "TOSEC",
            "Example (1999)(Publisher)(US)(Disc 2 of 3).zip",
        )

        media = result.records[0].media_parts[0]

        self.assertEqual(media.media_type, "disc")
        self.assertEqual(media.part, "2")
        self.assertEqual(media.sequence, 2)
        self.assertEqual(media.total, 3)


class DatExtractorTests(unittest.TestCase):
    def test_maybe_intro_dat_has_an_explicit_source_identity(self):
        result = DatExtractor._parse(
            "DatRoot/English Translations/Nintendo Super Famicom "
            "[T-En] (20121007).dat",
            "Nintendo Super Famicom [T-En]",
        )

        self.assertEqual(result.romset, "English Translations")
        self.assertEqual(result.source_manufacturer, "English Translations")
        self.assertEqual(result.source_system, "Nintendo Super Famicom")

    def test_tosec_dat_uses_path_manufacturer_and_system(self):
        result = DatExtractor._parse(
            "DatRoot/TOSEC/Acorn/Archimedes/Games/example.dat",
            "Acorn Archimedes - Games",
        )

        self.assertEqual(result.romset, "TOSEC")
        self.assertEqual(result.source_manufacturer, "Acorn")
        self.assertEqual(result.source_system, "Archimedes")
        self.assertEqual(result.additional, ("Games",))

    def test_no_intro_dat_uses_name_components(self):
        result = DatExtractor._parse(
            "DatRoot/No-Intro/Nintendo - Super Nintendo Entertainment System.dat",
            "Nintendo - Super Nintendo Entertainment System",
        )

        self.assertEqual(result.romset, "No-Intro")
        self.assertEqual(result.source_manufacturer, "Nintendo")
        self.assertEqual(result.source_system, "Super Nintendo Entertainment System")


class TranslationMemberTitleExtractorTests(unittest.TestCase):
    def test_original_title_is_recovered_from_localized_member_name(self):
        result = TranslationMemberTitleExtractor.extract(
            "Tenchi Muyou! - Game Hen (Japan) "
            "[T-En by borderLine+LNF v1.1].sfc"
        )

        self.assertEqual(result.title_candidate, "Tenchi Muyou! - Game Hen")
        self.assertEqual(result.status, "parsed")
