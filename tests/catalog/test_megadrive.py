from collections import Counter
import unittest

from gamedb.catalog.megadrive import ARCHIVE_MARKETS, add_cartridge_details, cartridge_records, mame_matches
from gamedb.catalog.megadrive_media import add_scans
from gamedb.catalog.megadrive_source import REVISION, parse_retail_list
from gamedb.catalog.references import SourceIndex
from gamedb.catalog.retail import match_archives


def source(rows):
    return f"""
    <html about="https://en.wikipedia.org/revision/{REVISION}">
    <h2 id="Licensed_games">Licensed games</h2>
    <table>
      <tr><th>Releases</th></tr>
      <tr><th>JP</th><th>NA</th><th>PAL</th><th>Other</th></tr>
      {rows}
    </table>
    <ol><li id="cite_note-channel">This game was exclusively released via the Sega Channel online game service.</li></ol>
    </html>
    """.encode()


class MegaDriveCatalogTests(unittest.TestCase):
    def test_network_dates_are_excluded_but_brazil_and_regional_credits_are_retained(self):
        html = source("""
          <tr><th>Nightmare Circus</th><td>Funcom</td><td>Sega<sup>NA/PAL</sup><br>Tec Toy<sup>BR</sup></td>
              <td>Unreleased</td><td>April 1996<sup class="reference"><a href="#cite_note-channel">[1]</a></sup></td>
              <td>Unreleased</td><td>1996<sup>BR</sup></td></tr>
          <tr><th>Iron Hammer</th><td>NovaLogic</td><td>Sega</td>
              <td>Unreleased</td><td>July 1996<sup class="reference"><a href="#cite_note-channel">[1]</a></sup></td>
              <td>Unreleased</td><td></td></tr>
        """)
        result = parse_retail_list(html, expected_rows=2)
        self.assertEqual(result["networkOnlyTitles"], ["Iron Hammer"])
        (game,) = result["games"]
        (release,) = game["releases"]
        self.assertEqual((release["market"], release["date"], release["publisher"]), ("BR", "1996", "Tec Toy"))
        with self.assertRaisesRegex(ValueError, "table layout"):
            parse_retail_list(html, expected_rows=3)

    def test_two_cartridge_conversions_keep_distinct_editions(self):
        result = parse_retail_list(source("""
          <tr><th rowspan="2">Klax</th><td>Namco</td><td>Namco</td>
              <td>September 7, 1990</td><td>Unreleased</td><td>Unreleased</td><td></td></tr>
          <tr><td>Tengen</td><td>Tengen</td>
              <td>Unreleased</td><td>1990</td><td>November 1991</td><td></td></tr>
        """), expected_rows=2)
        (game,) = result["games"]
        self.assertEqual(Counter(release["edition"] for release in game["releases"]),
                         {"Klax (Namco)": 1, "Klax (Tengen)": 2})
        self.assertEqual(len({release["key"] for release in game["releases"]}), 3)

    def test_reviewed_edition_keeps_each_manual_with_its_release(self):
        html = source("""
          <tr><th>Example</th><td>Studio</td><td>Sega</td>
              <td>Unreleased</td><td>1993</td><td>Unreleased</td><td></td></tr>
        """)
        evidence = {"name": "Box scan", "url": "https://example.com/scan"}
        catalog = parse_retail_list(html, additional_releases=[{
            "game": "Example", "edition": "Local Edition", "market": "NA", "source": evidence,
        }], expected_rows=1)
        add_scans(catalog, [], SourceIndex("https://example.com/manuals", b"""
            <a href="example.pdf">Example</a><a href="local.pdf">Local Edition</a>
        """))
        base, local = catalog["games"][0]["releases"]
        self.assertNotEqual(base["key"], local["key"])
        self.assertEqual(local["date"], "")
        self.assertEqual([r["manuals"][0]["name"] for r in (base, local)], ["Example", "Local Edition"])

    def test_mame_title_link_requires_verified_content_and_preserves_market_of_product_codes(self):
        catalog = parse_retail_list(source("""
          <tr><th>Streets of Rage 2<br>Bare Knuckle II<sup>JP</sup></th><td>Ancient</td><td>Sega</td>
              <td>January 14, 1993</td><td>Unreleased</td><td>January 1993</td><td></td></tr>
        """), expected_rows=1)
        signature = "a" * 32
        digest = "b" * 40
        archives = [{
            "title": "Streets of Rage 2", "signature": signature, "channel": "cartridge",
            "regions": ["EU", "JP"], "softwareKey": "a", "archiveNames": ["Streets of Rage 2.zip"],
        }]
        records = list(cartridge_records(f"""
          <softwarelist><software name="sor2">
          <description>Streets of Rage II (Europe) ~ Bare Knuckle II (Japan)</description>
          <info name="serial" value="G-4091 (JPN), MK-1057-50 (Euro)"/>
          <part><feature name="pcb" value="171-6329A"/><feature name="slot" value="rom_jcart"/><dataarea name="rom">
          <rom sha1="{digest}"/>
          </dataarea></part></software></softwarelist>
        """))
        match_archives(catalog, archives, [], markets=ARCHIVE_MARKETS)
        self.assertEqual(list(mame_matches(catalog, archives, {}, records)), [])
        roms = {signature: digest}
        verified = list(mame_matches(catalog, archives, roms, records))
        self.assertEqual([(record["market"], record["signature"]) for record in verified], [("JP", signature)])
        match_archives(catalog, archives, [], verified, markets=ARCHIVE_MARKETS)
        add_cartridge_details(catalog, roms, records)
        jp, pal = catalog["games"][0]["releases"]
        self.assertEqual(jp["archives"][0]["cartridge"][0]["serials"], ["G-4091"])
        self.assertEqual(pal["archives"][0]["cartridge"][0]["serials"], ["MK-1057-50"])
        self.assertEqual(pal["archives"][0]["cartridge"][0]["peripherals"], ["j-cart"])
        self.assertNotIn("candidates", jp)

    def test_scans_follow_the_release_market_and_prefer_physical_manuals(self):
        catalog = parse_retail_list(source("""
          <tr><th>Example</th><td>Studio</td><td>Sega</td>
              <td>1993</td><td>1993</td><td>Unreleased</td><td></td></tr>
        """), expected_rows=1)

        def scan(name, pages):
            return {
                "title": f"File:Example MD {name}.pdf", "fileusage": [{"title": "Example"}],
                "imageinfo": [{
                    "url": f"https://segaretro.org/images/{name.replace(' ', '_')}.pdf",
                    "descriptionurl": "https://segaretro.org/File:Example.pdf",
                    "mime": "application/pdf", "pagecount": pages,
                }],
            }

        add_scans(catalog, [
            ("Mega Drive Mini digital manuals", [scan("US MDMini manual", 32)], [], None),
            ("Mega Drive US manual scans", [scan("US Manual", 28)], [], None),
            ("Mega Drive EU manual scans", [scan("EU Manual", 48)], [], None),
        ])
        jp, na = catalog["games"][0]["releases"]
        self.assertNotIn("manuals", jp)
        (manual,) = na["manuals"]
        self.assertEqual(manual["regions"], ["US"])
        self.assertTrue(manual["url"].endswith("US_Manual.pdf"))
