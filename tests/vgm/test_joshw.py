import tempfile
import unittest
from pathlib import Path

from libarchive import file_writer

from gamedb.vgm.archives import open_vgm_location
from gamedb.vgm.fetch_joshw import packages
from gamedb.vgm.inventory import scan
from gamedb.vgm.joshw import soundtrack_name
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
                ("cdi", "jaguar/d/Defender 2000 (1996)(Atari)[Jaguar].7z", {}),
                ("spc", "h/Example (1994)(Data East)[SNES][old].7z", {"old": True}),
            )
        ])
        self.assertEqual({domain: [path.name for path, _, _ in rows] for domain, rows in selected.items()}, {
            "smd": ["After Burner Complete [32X](1995-01-13)(Rutubo)(Sega)[SMD].7z"],
            "kss": ["After Burner (SMS)(1987)(Sega).kss"],
            "cdi": ["Defender 2000 (1996)(Atari)[Jaguar].7z"],
        })

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

            album, = scan(root)
            add_track_tags(root, album.assets, {"mini2sf"})
            self.assertEqual(album.system, ("Nintendo", "Nintendo DS"))
            self.assertEqual((album.title, album.aliases), ("Actual Game", ("Regional Title",)))
            self.assertEqual(album.source_evidence["joshwPath"], source.relative_to(root / "JoshW").as_posix())
            self.assertEqual([asset["title"] for asset in album.assets if asset["kind"] == "track"], ["Menu", "Stage"])
            library, = [asset for asset in album.assets if asset["kind"] == "support"]
            with open_vgm_location(root, library) as stream:
                self.assertEqual(stream.read(), b"library")
