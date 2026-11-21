import tempfile
import unittest
from pathlib import Path
from struct import pack_into
from zipfile import ZipFile

from gamedb.vgm.importer import resolve
from gamedb.vgm.inventory import C64, GB, GBC, SNES, scan
from gamedb.vgm.matching import match_sid, psf_album, reviewed_titles, sid_claim
from gamedb.vgm.tags import read_tags


class InventoryTests(unittest.TestCase):
    def test_loose_spc_and_archive_copies_form_one_soundtrack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            label = "Final Fantasy 6 [ff6]"
            loose = root / "spcsets" / label
            loose.mkdir(parents=True)
            header = bytearray(256)
            magic = b"SNES-SPC700 Sound File Data"
            header[:len(magic)] = magic
            header[35] = 0x1A
            header[46:56] = b"Theme Song"
            (loose / "01.spc").write_bytes(header)
            (loose / "info.txt").write_text("Source credits")
            for parent in (root, root / "spcsets_tmp"):
                parent.mkdir(exist_ok=True)
                with ZipFile(parent / f"{label}.zip", "w") as archive:
                    archive.writestr("01.spc", header)
            (root / "spcsets" / "@eaDir").mkdir()
            (root / "spcsets" / "@eaDir" / "cache.spc").write_text("Ignored")

            album, = scan(root)
            self.assertEqual(album.title, "Final Fantasy 6")
            self.assertEqual(album.system, SNES)
            self.assertEqual(album.aliases, ())
            self.assertEqual(reviewed_titles()[(album.collection, label)]["catalog_title"],
                             "Final Fantasy III")
            self.assertEqual([asset["kind"] for asset in album.assets],
                             ["archive", "archive", "support", "track"])
            self.assertEqual(read_tags(root, album.assets[-1])["title"], "Theme Song")

    def test_gbs_platform_tags_and_review_only_composer_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in (
                "GBS/gbs.joshw.info/a/Example [Alternate] (1998)(Example)[GB].7z",
                "GBS/gbs.joshw.info/a/Example (1999)[GBC].7z",
                "C64Music/GAMES/A-F/Example.sid",
                "C64Music/MUSICIANS/A/Author/Example.sid",
                "C64Music/DEMOS/A-F/Example.sid",
            ):
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
            albums = scan(root)

        class CandidateRows:
            def execute(self, statement, params):
                self.rows = [
                    {"id": number, "name": name, "display_name": name,
                     "manufacturer_name": platform[0], "system_name": platform[1],
                     "target_key": str(number)}
                    for number, platform, name in (
                        (1, GB, "Alternate"), (2, GBC, "Example"),
                        (3, GBC, "Example"), (4, C64, "Example"),
                    )
                ]
                return self

            def mappings(self):
                return self.rows

        results = {(item.collection, tuple(item.system or ()),
                    item.source_name.split("/")[1] if item.collection == "C64Music" else ""):
                   result["status"]
                   for item, result in zip(albums, resolve(CandidateRows(), albums), strict=True)}
        self.assertEqual(results, {
            ("GBS", GB, ""): "matched",
            ("GBS", GBC, ""): "ambiguous",
            ("C64Music", C64, "GAMES"): "review",
            ("C64Music", C64, "MUSICIANS"): "review",
            ("C64Music", (), "DEMOS"): "unclassified",
        })

    def test_sid_release_credit_can_choose_between_catalog_homonyms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "C64Music/MUSICIANS/H/Author/Last_Ninja.sid"
            path.parent.mkdir(parents=True)
            header = bytearray(124)
            header[:4] = b"PSID"
            pack_into(">HH", header, 4, 2, 124)
            pack_into(">H", header, 14, 11)
            header[22:36] = b"The Last Ninja"
            header[54:60] = b"Author"
            header[86:99] = b"1987 System 3"
            path.write_bytes(header + b"\0\0")
            album, = scan(root)
            asset, = album.assets
            asset.update(read_tags(root, asset))
            claim = sid_claim(album)

        self.assertEqual(asset["subsongs"], 11)
        hits = {1: {}, 2: {}}
        credits = {1: {("1987", "system 3")}, 2: {("1988", "system 3")}}
        self.assertEqual(match_sid(hits, claim, credits), (1, "sid_year_and_publisher"))
        self.assertEqual(match_sid(hits, claim, {}), (None, None))
        self.assertEqual(match_sid({2: {}}, claim, credits), (None, None))

    def test_psf_game_tag_preserves_trial_title_and_decodes_japanese(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collection = root / "The PlayStation Music Collection PSF"
            for label in ("Example Game", "Example Game Trial"):
                folder = collection / label
                folder.mkdir(parents=True)
                for index in range(2):
                    header = bytearray(16)
                    header[:4] = b"PSF\x01"
                    pack_into("<II", header, 4, 4, 4)
                    tags = "[TAG]game=Example Game - The Adventure\r\ntitle=全ての始まり\n"
                    (folder / f"{index:02}.minipsf").write_bytes(
                        header + b"\0" * 8 + tags.encode("cp932")
                    )
            full, trial = scan(root)
            for album in (full, trial):
                for asset in album.assets:
                    asset.update(read_tags(root, asset))

        self.assertEqual(full.assets[0]["title"], "全ての始まり")
        self.assertEqual(psf_album(full), "Example Game - The Adventure")
        self.assertIsNone(psf_album(trial))


if __name__ == "__main__":
    unittest.main()
