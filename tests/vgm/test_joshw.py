import os
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from libarchive import file_writer

from gamedb.vgm.archives import open_vgm_location
from gamedb.vgm.fetch_joshw import link_playstation_packages, packages
from gamedb.vgm.importer import resolve
from gamedb.vgm.inventory import Soundtrack, scan
from gamedb.vgm.joshw import DEFAULT_SYSTEMS, PSF_COLLECTION, prefer_playstation_sources, soundtrack_name
from gamedb.vgm.matching import TitleIndex
from gamedb.vgm.tags import add_track_tags


class JoshWTests(unittest.TestCase):
    def test_regional_names_keep_the_source_edition(self):
        path = Path("Example Title [Regional Name] (Demo) (2007-09-10)(Developer)[NDS].7z")
        self.assertEqual(soundtrack_name("2sf", path), ("Example Title (Demo)", ("Regional Name (Demo)",)))

    def test_selection_reads_media_tags_and_platform_folders(self):
        selected = packages([
            {"sd": domain, "nm": name, "sz": 256, "md": "2026-11-17 10:47", **flags}
            for domain, name, flags in (
                ("smd", "m/MegaRace [SCD](1993)(Cryo)[SMD].7z", {}),
                ("smd", "a/After Burner Complete [32X](1995-01-13)(Rutubo)(Sega)[SMD].7z", {}),
                ("hes", "m/Mad Stalker (1994-09-15)(NEC)[TCD][tagged].7z", {}),
                ("kss", "MSX/a/Aleste.7z", {}),
                ("kss", "Master System/a/After Burner (SMS)(1987)(Sega).kss", {}),
                ("cdi", "atari_st/c/Example [AtariST].7z", {}),
                ("cdi", "amiga/h/Heimdall 2 (CD32) (1994)(Core Design)[Amiga].7z", {}),
                ("cdi", "jaguar/d/Defender 2000 (1996)(Atari)[Jaguar].7z", {}),
                ("spc", "h/Example (1994)(Data East)[SNES][old].7z", {"old": True}),
            )
        ])
        self.assertEqual({domain: [path.name for path, _, _ in rows] for domain, rows in selected.items()}, {
            "smd": ["After Burner Complete [32X](1995-01-13)(Rutubo)(Sega)[SMD].7z"],
            "kss": ["After Burner (SMS)(1987)(Sega).kss"],
            "cdi": ["Defender 2000 (1996)(Atari)[Jaguar].7z"],
        })

    def test_fetch_uses_the_fixed_copy_of_each_version(self):
        names = [f"z/Example (v{version}){fix} (1998)(Nintendo)[N64].7z"
                 for version, fix in (("1.0", ""), ("1.0", " [fixed]"), ("1.2", ""))]
        index = [{"sd": "usf", "nm": name, "sz": 256, "md": "2026-11-17 10:47"} for name in names]
        self.assertEqual([str(path) for path, _, _ in packages(index)["usf"]], names[1:])

    def test_playstation_archives_reuse_the_indexed_version(self):
        name = "t/Test Game (2000)(Studio)[PS1].7z"
        entries = packages([{"sd": "psf", "nm": name, "sz": 7, "md": "2018-11-20 17:57"}])["psf"]
        path, _, revision = entries[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / PSF_COLLECTION / path.name
            legacy.parent.mkdir()
            legacy.write_bytes(b"archive")
            os.utime(legacy, (revision - 60, revision - 60))
            self.assertEqual(link_playstation_packages(root / "JoshW", entries), 0)
            os.utime(legacy, (revision, revision))
            self.assertEqual(link_playstation_packages(root / "JoshW", entries), 1)
            self.assertTrue((root / "JoshW" / "psf" / path).samefile(legacy))
            self.assertEqual(link_playstation_packages(root / "JoshW", entries), 0)
            self.assertEqual(DEFAULT_SYSTEMS["psf"], ("Sony", "PlayStation"))

    def test_preferred_playstation_source_covers_the_same_release(self):
        name = "Test Game (2000)(Studio)[PS1]"
        legacy = {"collection": PSF_COLLECTION, "sourceName": name, "releases": ["us"],
                  "assets": [{"kind": "track", "format": "xa"}]}
        joshw = {**legacy, "collection": "JoshW", "sourceName": f"psf/t/{name}"}
        other = {**legacy, "sourceName": "Test Game (Alternate)"}
        self.assertEqual(prefer_playstation_sources([joshw, legacy, other]), [joshw, other])
        japanese = {**joshw, "releases": ["jp"]}
        self.assertEqual(prefer_playstation_sources([japanese, legacy]), [japanese, legacy])
        unavailable = {**joshw, "assets": [{"kind": "archive"}]}
        self.assertEqual(prefer_playstation_sources([unavailable, legacy]), [unavailable, legacy])

    def test_versioned_title_matches_both_catalog_names_only_with_revision_evidence(self):
        system = DEFAULT_SYSTEMS["usf"]
        english = "Legend of Zelda, The - Ocarina of Time"
        japanese = "Zelda no Densetsu - Toki no Ocarina"
        title, aliases = soundtrack_name("usf", Path(
            f"{english} [{japanese}] (v1.2) [fixed] (1998-11-21)(Nintendo)[N64].7z"
        ))
        self.assertEqual((title, aliases), (f"{english} (v1.2) [fixed]", (japanese,)))
        album = Soundtrack("set", "JoshW", "ocarina", title, system, aliases)
        index = TitleIndex([(system, name) for name in (english, japanese)], spelling_systems={system})
        for ident, name in enumerate((english, japanese, f"{english} - Master Quest"), 1):
            index.add(system, {"id": ident, "name": name, "display_name": name, "target_key": str(ident)})

        versions = defaultdict(set, {1: {("revision", "2")}, 2: {("revision", "0")}})
        with (patch("gamedb.vgm.importer.catalog_index", return_value=index),
              patch("gamedb.vgm.importer.release_versions", return_value=versions)):
            row, = resolve(None, [album])
            self.assertEqual((row["target_key"], row["additional_target_keys"]), ("1", []))
            versions[2].add(("revision", "2"))
            row, = resolve(None, [album])
            self.assertEqual((row["target_key"], row["additional_target_keys"]), ("1", ["2"]))
            self.assertEqual(row["match_evidence"]["joshwVersion"], "1.2")

    def test_reviewed_game_boy_gallery_rip_keeps_the_australian_title(self):
        source = "gbs/g/Game & Watch Gallery [Game Boy Gallery] [Game Boy Gallery 2] (1997-02-01)(Tose)(Nintendo)[SGB]"
        system = DEFAULT_SYSTEMS["gbs"]
        title, aliases = soundtrack_name("gbs", Path(f"{source}.7z"))
        names = (title, *aliases)
        index = TitleIndex([(system, name) for name in names], spelling_systems={system})
        for ident, name in enumerate(names, 1):
            index.add(system, {"id": ident, "name": name, "display_name": name, "target_key": str(ident)})
        album = Soundtrack("set", "JoshW", source, title, system, aliases)

        with patch("gamedb.vgm.importer.catalog_index", return_value=index):
            row, = resolve(None, [album])
        self.assertEqual((row["target_key"], row["additional_target_keys"]), ("1", ["3"]))
        self.assertIn("DMG-AGAU", row["match_evidence"]["additionalTitles"][0]["reviewNote"])

    def test_joshw_cd32_archive_keeps_disc_audio_modules_and_short_title(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "JoshW/cdi/amiga/h/Heimdall 2 - Into the Hall of Worlds (CD32)(1994)[Amiga].7z"
            source.parent.mkdir(parents=True)
            tracks = {"02_title.ogg": b"disc audio", "mod.title": b"tracked intro",
                      "archive.txt": "type: Game\ntitle: Heimdall 2 (CD³²)\n".encode("cp1252")}
            with file_writer(str(source), "7zip") as archive:
                for name, data in tracks.items():
                    archive.add_file_from_memory(name, len(data), data)
            album, = scan(root)
            self.assertEqual(album.system, ("Commodore", "Amiga CD32"))
            self.assertEqual(album.title, "Heimdall 2 - Into the Hall of Worlds")
            self.assertEqual(album.source_evidence["joshwDiscTitle"], "Heimdall 2")
            self.assertEqual(album.aliases, ("Heimdall 2",))
            self.assertEqual([asset["format"] for asset in album.assets if asset["kind"] == "track"], ["ogg", "mod"])

    def test_7zip_album_keeps_title_and_shared_2sf_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "JoshW/2sf/a/Actual Game [Regional Title] (2008-05)(Studio)[NDS].7z"
            source.parent.mkdir(parents=True)
            recordings = {
                "Album/01.mini2sf": b"PSF\x24" + b"\0" * 12 + b"[TAG]title=Menu\n_lib=album.2sflib\n",
                "Album/02.mini2sf": b"PSF\x24" + b"\0" * 12 + b"[TAG]title=Stage\n_lib=album.2sflib\n",
                "Album/album.2sflib": b"library",
                "Album/unrelated.bin": b"ignored",
            }
            with file_writer(str(source), "7zip") as archive:
                for path, data in recordings.items():
                    archive.add_file_from_memory(path, len(data), data)

            (root / "Unrelated.nsf").write_bytes(b"NESM\x1a")
            album, = scan(root, subdirectory=Path("JoshW/2sf"))
            add_track_tags(root, album.assets, {"mini2sf"})
            self.assertEqual(album.system, ("Nintendo", "Nintendo DS"))
            self.assertEqual((album.title, album.aliases), ("Actual Game", ("Regional Title",)))
            self.assertEqual(album.source_evidence["joshwPath"], source.relative_to(root / "JoshW").as_posix())
            self.assertEqual([asset["title"] for asset in album.assets if asset["kind"] == "track"], ["Menu", "Stage"])
            library, = [asset for asset in album.assets if asset["kind"] == "support"]
            with open_vgm_location(root, library) as stream:
                self.assertEqual(stream.read(), b"library")
