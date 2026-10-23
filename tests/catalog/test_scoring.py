import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ScoringContractTests(unittest.TestCase):
    def test_bonus_disc_is_an_explicit_media_label_penalty(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("'media_label', 'equals', 'Bonus Disc', -500", preferences)
        self.assertNotIn("'media_label', 'present'", preferences)

    def test_undubs_are_explicitly_preferred(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("'dump_modification', 'equals', 'undub', 150", preferences)

    def test_default_policy_names_contextual_translation_roles(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("preferred_language_fallback", preferences)
        self.assertIn("'translation_role', 'equals', 'redundant'", preferences)
        self.assertIn("'translation_role', 'equals', 'nonpreferred'", preferences)

    def test_preferences_support_exact_system_overrides(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")
        generation = (
            PROJECT_ROOT / "sql/layers/scoring/020_generate_scores.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("system_manufacturer, system_name", preferences)
        self.assertIn("'Atari', 'ST'", preferences)
        self.assertIn(
            "preference.system_id IS NULL OR preference.system_id = title.system_id",
            generation,
        )

    def test_virtual_console_is_an_explicit_distribution_penalty(self):
        preferences = (
            PROJECT_ROOT / "sql/layers/scoring/010_preferences.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("'virtual_console', -100", preferences)
        self.assertIn("'wii_u_virtual_console', -100", preferences)


if __name__ == "__main__":
    unittest.main()
