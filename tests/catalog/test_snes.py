from hashlib import md5
import json
import os
import unittest

from sqlalchemy import text

from gamedb.catalog.snes import BASE_ARCHIVES, SUFAMI_SYSTEM, SYSTEM_NAME, match_archives
from gamedb.catalog.snes_source import REVISION, parse_retail_list
from gamedb.database import create_database_engine


def source_document(rows, revision=REVISION):
    return f"""<html about="//en.wikipedia.org/wiki/Special:Redirect/revision/{revision}">
    <h2 id="Retail_releases">Retail releases</h2>
    <table><tbody>
      <tr><th>Title</th><th>Developer(s)</th><th>Publisher(s)</th><th>Release date</th><th>Ref.</th></tr>
      <tr><th>Japan</th><th>North America</th><th>PAL region</th></tr>
      {rows}
    </tbody></table>
    <li id="cite_note-digital">Digital release only (Nintendo Power).</li>
    <h2 id="Unlicensed_games">Unlicensed games</h2><table><tr><td>Other title</td></tr></table>
    </html>""".encode()


def row(title, japan="Unreleased", north_america="Unreleased", pal="Unreleased"):
    return (f"<tr><td>{title}</td><td>Developer</td><td>Publisher</td>"
            f"<td>{japan}</td><td>{north_america}</td><td>{pal}</td></tr>")


def archive(title, signature, regions, *, channel="cartridge", software_key="software"):
    return {"title": title, "signature": signature, "regions": regions, "archiveNames": [f"{title}.zip"],
            "channel": channel, "softwareKey": software_key}


class SnesRetailTests(unittest.TestCase):
    def test_regional_aliases_and_edition_keep_their_own_release_records(self):
        not_released = 'Unreleased<sup class="reference"><a href="#cite_note-f">[f]</a></sup>'
        html = source_document(
            row('<span class="sortkey">Game, English</span><i>English Game<span class="noprint"> [ja]</span></i>'
                '<br><i>Nihon Game</i><sup>JP</sup><p>•<i>PAL Game</i><sup>PAL</sup></p>',
                "July 1992", "1993", "April 1993")
            + row("English Game: Easy Edition", "October 1992", not_released, "Cancelled")
        )
        catalog = parse_retail_list(html, {"English Game: Easy Edition": "English Game"}, expected_rows=2)
        self.assertEqual(catalog["source"]["rowCount"], 2)
        game, = catalog["games"]
        self.assertEqual(game["title"], "English Game")
        self.assertEqual([(r["market"], r["titles"], r["date"]) for r in game["releases"]], [
            ("JP", ["Nihon Game"], "July 1992"), ("NA", ["English Game"], "1993"),
            ("PAL", ["PAL Game"], "April 1993"), ("JP", ["English Game: Easy Edition"], "October 1992"),
        ])
        self.assertEqual(len({r["key"] for r in game["releases"]}), 4)

    def test_wrong_revision_and_partial_tables_cannot_be_loaded(self):
        with self.assertRaisesRegex(ValueError, "Expected Wikipedia revision"):
            parse_retail_list(source_document(row("Game", "1993"), revision=1), {}, expected_rows=1)
        with self.assertRaisesRegex(ValueError, "Expected 2 SNES retail rows"):
            parse_retail_list(source_document(row("Game", "1993")), {}, expected_rows=2)

    def test_review_note_is_attached_to_the_documented_market(self):
        note = {"edition": "Game", "market": "PAL", "text": "Possible prototype",
                "url": "https://example.com/source"}
        catalog = parse_retail_list(source_document(row("Game", "1993", "Unreleased", "1994")),
                                    {}, release_notes=[note], expected_rows=1)
        japan, pal = catalog["games"][0]["releases"]
        self.assertNotIn("reviewNote", japan)
        self.assertEqual(pal["reviewNote"], {"text": note["text"], "url": note["url"]})

    def test_bracketed_language_link_does_not_become_part_of_the_title(self):
        title = ('<i>Chaos Seed</i> <span about="#mwt1">[</span><span about="#mwt1">'
                 '<a rel="mw:WikiLink/Interwiki">ja</a></span><span about="#mwt1">]</span>')
        catalog = parse_retail_list(source_document(row(title, "1996")), {}, expected_rows=1)
        self.assertEqual(catalog["games"][0]["title"], "Chaos Seed")

    def test_base_matches_use_documented_market_and_distribution(self):
        html = source_document(
            row('Game <sup class="reference"><a href="#cite_note-digital">[c]</a></sup>', "1999")
            + row("Other Game", "Unreleased", "1994", "1995")
        )
        catalog = parse_retail_list(html, {}, expected_rows=2)
        match_archives(catalog, [
            archive("Game", "wrong-channel", ["JP"]),
            archive("Game", "wrong-market", ["US"], channel="nintendo-power"),
            archive("Game", "correct", ["JP"], channel="nintendo-power"),
            archive("Other Game", "usa", ["US"]),
            archive("Other Game", "europe", ["DE"]),
        ], [])
        self.assertEqual(catalog["summary"]["matched"], 3)
        self.assertEqual([
            r["archives"][0]["signature"] for g in catalog["games"] for r in g["releases"]
        ], ["correct", "usa", "europe"])

    def test_content_claimed_by_two_editions_stays_reviewable(self):
        html = source_document(row("First Game", "1992") + row("Second Game", "1994"))
        catalog = parse_retail_list(html, {}, expected_rows=2)
        match_archives(catalog, [archive("Cartridge Name", "same-content", ["JP"])], [
            {"edition": "First Game", "market": "JP", "archiveTitle": "Cartridge Name"},
            {"edition": "Second Game", "market": "JP", "archiveTitle": "Cartridge Name"},
        ])
        self.assertEqual(catalog["summary"]["ambiguous"], 2)
        for game in catalog["games"]:
            release, = game["releases"]
            self.assertNotIn("archives", release)
            self.assertEqual(release["candidates"][0]["basis"], "reviewed-alias-and-region")

    def test_spelling_matches_keep_numbers_and_defer_to_direct_claims(self):
        html = source_document(row("Kōha 2", "1992") + row("ClayFighter", "1994")
                               + row("Clay Fighter", "1994"))
        catalog = parse_retail_list(html, {}, expected_rows=3)
        match_archives(catalog, [
            archive("Kouha 2", "sequel", ["JP"]), archive("Kouha", "original", ["JP"]),
            archive("Clay Fighter", "clay", ["JP"]),
        ], [])
        sequel, variant, direct = [game["releases"][0] for game in catalog["games"]]
        self.assertEqual([(match["signature"], match["basis"]) for match in sequel["archives"]],
                         [("sequel", "spelling-and-region")])
        self.assertEqual(variant["status"], "ambiguous")
        self.assertEqual(direct["status"], "matched")

    def test_dat_articles_before_subtitles_match_the_published_title(self):
        html = source_document(row("The Game: Its Subtitle", "1994"))
        catalog = parse_retail_list(html, {}, expected_rows=1)
        match_archives(catalog, [archive("Game, The - Its Subtitle", "correct", ["JP"])], [])
        self.assertEqual(catalog["summary"]["gamesWithMatches"], 1)

    def test_verified_revisions_can_span_archive_software_groups(self):
        catalog = parse_retail_list(source_document(row("Game", "Unreleased", "1994")), {}, expected_rows=1)
        original, revision, foreign, different_game = [f"{number:032x}" for number in range(1, 5)]
        match_archives(catalog, [
            archive("Game", original, ["US"]),
            archive("Game", revision, ["US"], software_key="separate-archive-software"),
            archive("Game", foreign, ["JP"]),
            archive("Game", different_game, ["US"], software_key="unrelated-software"),
        ], [], [{"edition": "Game", "market": "NA", "signature": signature, "evidence": "Cartridge SHA-1"}
                for signature in [original, revision, foreign]])
        release, = catalog["games"][0]["releases"]
        self.assertEqual(release["status"], "matched")
        self.assertEqual([item["signature"] for item in release["archives"]], [original, revision])


@unittest.skipUnless(os.environ.get("GAMEDB_TEST_POSTGRES") == "1", "requires PostgreSQL")
class SnesBaseArchiveTests(unittest.TestCase):
    def test_original_inventory_excludes_modifications_and_unknown_distribution_flags(self):
        engine = create_database_engine()
        self.addCleanup(engine.dispose)
        sql = BASE_ARCHIVES.text.replace("catalog.", "pg_temp.").replace("derived.", "pg_temp.")
        with engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql("""
                    CREATE TEMP TABLE system (id int, manufacturer_name text, system_name text) ON COMMIT DROP;
                    CREATE TEMP TABLE software (id int, system_id int, preferred_title_id int, identity_basis text,
                        source_snapshot_key text, source_software_id int, source_group_key text) ON COMMIT DROP;
                    CREATE TEMP TABLE title (id int, cluster_key text) ON COMMIT DROP;
                    CREATE TEMP TABLE software_release (software_id int, release_id int) ON COMMIT DROP;
                    CREATE TEMP TABLE release (id int, display_title text) ON COMMIT DROP;
                    CREATE TEMP TABLE release_content_signature (release_id int, sha1_set_digest text) ON COMMIT DROP;
                    CREATE TEMP TABLE release_package (release_id int, package_id int, source_archive_name_id int,
                        source_record_index int) ON COMMIT DROP;
                    CREATE TEMP TABLE package (id int, archive_name text, source_collection text, resolved_path text) ON COMMIT DROP;
                    CREATE TEMP TABLE package_file (package_id int, sha1_verified bool) ON COMMIT DROP;
                    CREATE TEMP TABLE release_fact (release_id int, fact_key text, fact_value text) ON COMMIT DROP;
                    CREATE TEMP TABLE tag_classification (archive_name_id int, record_index int,
                        classification_status text) ON COMMIT DROP;

                    INSERT INTO system VALUES (1, 'Nintendo', 'Super Nintendo Entertainment System');
                    INSERT INTO title VALUES (1, 'Game');
                    INSERT INTO software VALUES (1, 1, 1, 'title_fallback', NULL, NULL, NULL);
                    INSERT INTO release SELECT i, 'Game' FROM generate_series(1, 6) i;
                    INSERT INTO software_release SELECT 1, id FROM release;
                    INSERT INTO release_content_signature SELECT id, md5(id::text) FROM release;
                    INSERT INTO release_package SELECT id, id, id, 1 FROM release;
                    INSERT INTO package SELECT id, id || '.zip',
                        CASE id WHEN 5 THEN 'English Translations' ELSE 'No-Intro' END, '/archive.zip' FROM release;
                    INSERT INTO package_file SELECT id, id <> 6 FROM release;
                    INSERT INTO release_fact SELECT id, 'region', 'JP' FROM release;
                    INSERT INTO release_fact VALUES (3, 'distribution_channel', 'virtual_console'),
                        (4, 'dump_modification', 'hacked');
                    INSERT INTO tag_classification VALUES (2, 1, 'unclassified');
                """)
                params = {"system": SYSTEM_NAME, "sufami": SUFAMI_SYSTEM, "verified_labels": "{}"}
                releases = connection.execute(text(sql), params).mappings().all()
                self.assertEqual([release["archiveNames"] for release in releases], [["1.zip"]])
                params["verified_labels"] = json.dumps({md5(b"2").hexdigest(): "wrong-label.zip"})
                releases = connection.execute(text(sql), params).mappings().all()
                self.assertEqual([release["archiveNames"] for release in releases], [["1.zip"]])
                params["verified_labels"] = json.dumps({md5(str(number).encode()).hexdigest(): f"{number}.zip"
                                                        for number in (2, 3, 4, 5, 6)})
                releases = connection.execute(text(sql), params).mappings().all()
                self.assertEqual([release["archiveNames"] for release in releases], [["1.zip"], ["2.zip"]])
