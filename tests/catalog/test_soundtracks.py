import unittest

from gamedb.catalog.soundtracks import SNES, link_soundtracks
from gamedb.vgm.inventory import PLAYSTATION
from gamedb.vgm.joshw import COLLECTION


def release(key, edition, title, market, date, software_key, versions=()):
    return {
        "key": key, "edition": edition, "titles": [title], "market": market, "date": date,
        "channel": "cartridge", "status": "matched",
        "archives": [{"title": title, "softwareKey": software_key, "versions": versions, "revisions": []}],
    }


def album(key, title, label, target=None):
    return {
        "key": key, "title": title, "source_name": label, "target_key": target,
        "platform": SNES, "collection": COLLECTION, "aliases": [], "additional_target_keys": [],
        "status": "matched" if target else "unmatched",
    }


class SoundtrackTests(unittest.TestCase):
    def test_release_date_resolves_two_games_named_casper(self):
        japanese = {"releases": [release("jp", "Casper (Japan)", "Casper", "JP", "March 14, 1997", "shared")]}
        western = {"releases": [release("na", "Casper", "Casper", "NA", "December 1996", "shared")]}
        catalog = {"games": [japanese, western]}

        self.assertEqual(link_soundtracks(catalog, [
            album("kss", "Casper", "Casper (1997-03-14)(Natsume)(KSS)[SNES]", "shared"),
            album("imagineering", "Casper", "Casper (1996-12)(Imagineering)[SNES]", "shared"),
            album("undated", "Casper", "Casper [SNES]", "shared"),
        ]), {"titles": 2, "sets": 2})
        self.assertEqual([(link["key"], link["releases"]) for link in japanese["soundtrackLinks"]], [("kss", ["jp"])])
        self.assertEqual([(link["key"], link["releases"]) for link in western["soundtrackLinks"]],
                         [("imagineering", ["na"])])

    def test_specific_edition_and_deferred_sets(self):
        game = {"releases": [
            release("jp", "Final Fantasy IV", "Final Fantasy IV", "JP", "July 19, 1991", "shared"),
            release("na", "Final Fantasy IV", "Final Fantasy II", "NA", "November 1991", "shared"),
            release("easy", "Final Fantasy IV Easy Type", "Final Fantasy IV Easy Type", "JP", "October 29, 1991", "shared"),
        ]}
        other = {"releases": [release("other", "Other Game", "Other Game", "JP", "1993", "other")]}
        deferred = "Final Fantasy IV (alt) [SNES]"

        self.assertEqual(link_soundtracks({"games": [game, other]}, [
            album("iv", "Final Fantasy IV", "Final Fantasy IV (1991-07-19)[SNES]", "shared"),
            album("wrong-owner", "Final Fantasy IV Easy Type", "Final Fantasy IV Easy Type [SNES]", "other"),
            album("prototype", "Final Fantasy IV (Prototype)", "Final Fantasy IV (Prototype) [SNES]", "shared"),
            album("deferred", "Final Fantasy IV", deferred, "shared"),
        ], reviews={(COLLECTION, deferred): {"catalog_title": ""}}), {"titles": 1, "sets": 1})
        self.assertEqual(game["soundtrackLinks"], [{
            "key": "iv", "title": "Final Fantasy IV", "collection": COLLECTION,
            "releases": ["jp", "na"], "titleMatches": ["jp"],
        }])

    def test_explicit_market_and_version_and_fixed_archives(self):
        game = {"releases": [
            release("jp", "Game", "Game", "JP", "1993", "same", ["1.1"]),
            release("na", "Game", "Game", "NA", "1993", "same", ["1.1"]),
            release("pal", "Game", "Game", "PAL", "1994", "same", ["1.0"]),
        ]}
        name = "Game (v1.1) (1993)[JP][SNES]"

        self.assertEqual(link_soundtracks({"games": [game]}, [
            album("old", "Game (v1.1)", name),
            album("fixed", "Game (v1.1) [fixed]", name + " [fixed]"),
            album("wrong-version", "Game (v1.2)", "Game (v1.2) (1993)[JP][SNES]"),
        ]), {"titles": 1, "sets": 1})
        self.assertEqual([(link["key"], link["releases"]) for link in game["soundtrackLinks"]], [("fixed", ["jp"])])

    def test_playstation_demo_alias_does_not_link_to_a_retail_release(self):
        game = {"releases": [release("na", "Game", "Game", "NA", "1999", "base")]}
        retail = {**album("retail", "Game", "psf/g/Game (1999)[PS1]", "base"), "platform": PLAYSTATION}
        demo = {**album("demo", "Game", "psf/g/Game [Euro Demo 37] (1999)[PS1]", "base"), "platform": PLAYSTATION}
        result = link_soundtracks({"games": [game]}, [demo, retail], system=PLAYSTATION, secondary_platform=None)
        self.assertEqual(result, {"titles": 1, "sets": 1})
        self.assertEqual([link["key"] for link in game["soundtrackLinks"]], ["retail"])
