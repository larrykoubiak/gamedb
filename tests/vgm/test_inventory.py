import tempfile
import unittest
from gzip import compress
from io import BytesIO
from pathlib import Path
from struct import pack, pack_into
from unittest.mock import patch
from zipfile import ZipFile

from gamedb.vgm.amiga import AMIGA_CD32
from gamedb.vgm.archives import open_vgm_location
from gamedb.vgm.importer import resolve
from gamedb.vgm.inventory import C64, GB, GBC, SNES, ST, Soundtrack, identify, scan
from gamedb.vgm.matching import TitleIndex, match_sid, psf_album, reviewed_titles, sid_claim
from gamedb.vgm.tags import read_tags, stream_tags


def stored_lha_member(name, contents):
    # Level-zero LHA header, stored payload and the CRC-16 of that payload.
    filename = name.encode("ascii")
    crc = 0
    for byte in contents:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    header = pack("<5sIIIBBB", b"-lh0-", len(contents), len(contents),
                  0x210000, 0x20, 0, len(filename)) + filename + pack("<H", crc)
    return bytes((len(header), sum(header) % 256)) + header + contents


class InventoryTests(unittest.TestCase):
    def test_unexotica_readable_tracks_keep_prefix_names_and_disc_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "UnExotica/Game/Composer/Test_CD32.lha"
            path.parent.mkdir(parents=True)
            path.write_bytes(
                stored_lha_member("Music/MOD.Menu ", b"module")
                + stored_lha_member("Music/smpl.Menu", b"samples")
                + stored_lha_member("../mod.outside", b"outside")
                + b"\0"
            )
            path.with_suffix(".txt").write_bytes(
                "source type\nGame\nsource title\nActual Game (CD³²)\n"
                "alternative titles\nAnother Name\nformat\nProTracker\n".encode("cp1252")
            )
            album, = scan(root)
            self.assertEqual(album.system, AMIGA_CD32)
            self.assertEqual(album.title, "Actual Game")
            self.assertEqual(album.aliases, ("Another Name",))
            self.assertFalse(album.review_only)
            self.assertEqual(album.match_basis, "unexotica_game_notes")
            self.assertEqual(album.source_evidence["unexoticaSourceTitle"], "Actual Game (CD³²)")
            track, = [asset for asset in album.assets if asset["kind"] == "track"]
            self.assertEqual((track["name"], track["format"]), ("MOD.Menu ", "mod"))
            self.assertNotIn("mod.outside", [asset["name"] for asset in album.assets])
            self.assertIn(("smpl.Menu", "support"), [(asset["name"], asset["kind"]) for asset in album.assets])
            with open_vgm_location(root, track) as stream:
                stream.seek(1)
                self.assertEqual(stream.read(3), b"odu")
            changed = {**track, "archive_size_bytes": track["archive_size_bytes"] + 1}
            with self.assertRaisesRegex(ValueError, "Soundtrack archive changed"):
                with open_vgm_location(root, changed):
                    self.fail("A changed archive must not be opened")

    def test_sndh_matching_uses_long_names_outside_demo_folders(self):
        for relative, review in (
            ("sndh_lf/Author/Example.sndh", False),
            ("sndh_lf/Author/Games/Example.sndh", False),
            ("sndh_lf/Author/Demos/Example.sndh", True),
            ("sndh_sf/author/example.snd", True),
        ):
            _, _, platform, review_only = identify(Path(relative))
            self.assertEqual(platform, ST)
            self.assertEqual(review_only, review)

    def test_game_boy_tags_read_the_subsong_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "The GameBoy Music Collection/Example.gbs"
            path.parent.mkdir()
            header = bytearray(112)
            header[:6] = b"GBS\x01\x03\x01"
            header[16:23] = b"Example"
            header[48:54] = b"Author"
            path.write_bytes(header)
            album, = scan(root)
            self.assertEqual(read_tags(root, album.assets[0]), {
                "album": "Example", "artist": "Author", "copyright": "", "subsongs": 3,
            })

    def test_vgm_and_vgz_use_the_gd3_author(self):
        for english, japanese, expected in (("Composer", "作曲者", "Composer"), ("", "作曲者", "作曲者")):
            fields = ["Opening", "", "Example", "", "Mega Drive", "", english, japanese,
                      "1992", "Ripper", ""]
            tags = ("\0".join(fields) + "\0").encode("utf-16-le")
            header = bytearray(0x40)
            header[:4] = b"Vgm "
            pack_into("<I", header, 0x14, len(header) + 1 - 0x14)
            vgm = header + b"\x66Gd3 " + pack("<II", 0x100, len(tags)) + tags
            for name, data in (("vgm", vgm), ("vgz", compress(vgm))):
                with self.subTest(format=name, expected=expected):
                    asset = {"format": name, "size_bytes": len(data)}
                    with tempfile.SpooledTemporaryFile() as stream:
                        stream.write(data)
                        stream.seek(0)
                        self.assertEqual(stream_tags(stream, asset), {"artist": expected})
            self.assertEqual(stream_tags(BytesIO(vgm[:-1]), {"format": "vgm", "size_bytes": len(vgm)}), {})

    def test_nsfe_reads_the_author_chunk_after_the_music(self):
        auth = "Game\0Composer A, Composer B\0Publisher\0Ripper\0".encode()
        data = b"NSFE" + pack("<I4s", 512, b"DATA") + bytes(512)
        data += pack("<I4s", len(auth), b"auth") + auth
        asset = {"format": "nsfe", "size_bytes": len(data)}
        self.assertEqual(stream_tags(BytesIO(data), asset), {"artist": "Composer A, Composer B"})
        self.assertEqual(stream_tags(BytesIO(data[:-1]), asset), {})

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

    def test_reviewed_hvsc_relocation_can_keep_the_existing_game_link(self):
        title = "Old Tower"
        path = "C64Music/MUSICIANS/N/Nikitin_Oleg/Old_Tower"
        album = Soundtrack("set", "C64Music", path, title, C64, review_only=True)
        candidates = TitleIndex([(C64, title)])
        candidates.add(C64, {"id": 1, "name": title, "display_name": title, "target_key": "old-tower"})
        with patch("gamedb.vgm.importer.catalog_index", return_value=candidates):
            row, = resolve(None, [album])
        self.assertEqual(row["target_key"], "old-tower")
        self.assertEqual(row["match_evidence"]["basis"], "reviewed_title")

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
