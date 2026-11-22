import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from zlib import crc32

from gamedb.catalog.snes_translations import (
    INDEX_NAME, BaseRoms, _documented_input, _import_translations, _package_matches,
)
from gamedb.explorer.related_media import (
    add_local_translations, add_translation_availability, _open_translation, _translation_location,
)


IPS = b"PATCH\x00\x00\x01\x00\x01xEOF"


def rom(seed, signature):
    data = bytes([seed]) * 130
    return SimpleNamespace(sha1=hashlib.sha1(data).hexdigest(), crc32=f"{crc32(data):08x}",
                           md5=hashlib.md5(data).hexdigest(), size=len(data), signature=signature)


def checked_patch(base, patch_format):
    # These examples copy a 130-byte input as the target.
    header = {"bps": b"BPS1\x02\x80\x02\x80\x80\x04\x83", "ups": b"UPS1\x02\x80\x02\x80"}[patch_format]
    content = header + int(base.crc32, 16).to_bytes(4, "little") * 2
    return content + crc32(content).to_bytes(4, "little")


def archive(path, members):
    with ZipFile(path, "w") as handle:
        for filename, payload in members.items():
            handle.writestr(filename, payload)


class SnesTranslationsTests(unittest.TestCase):
    def test_multi_patch_archive_uses_each_embedded_input(self):
        first, second = rom(1, "first"), rom(2, "second")
        bases = BaseRoms([first, second])
        row = {"patchhint": 4, "patchstatus": 1, "rominfo": f"CRC32: {first.crc32}"}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "multiple.zip"
            archive(path, {
                "first.bps": checked_patch(first, "bps"),
                "second.ups": checked_patch(second, "ups"),
                "other.ips": IPS,
                "bad.bps": checked_patch(first, "bps")[:-1] + b"\xff",
                "../unsafe.bps": checked_patch(first, "bps"),
            })
            matches, reason = _package_matches(row, path, bases)
            self.assertIsNone(reason)
            self.assertEqual([(name, base["sha1"], layout, evidence) for name, _, _, base, layout, evidence in matches], [
                ("first.bps", first.sha1, "headerless", "embedded"),
                ("second.ups", second.sha1, "headerless", "embedded"),
            ])
            different_size = BaseRoms([SimpleNamespace(**{**vars(first), "size": 131})])
            self.assertEqual(_package_matches(row, path, different_size)[0], [])

    def test_ips_needs_consistent_source_hashes_and_a_single_patch(self):
        first, second = rom(1, "first"), rom(2, "second")
        bases = BaseRoms([first, second])
        info = (f"File SHA-1: {'a' * 40}\r\nROM SHA-1: {first.sha1}\r\nROM CRC32: {first.crc32}"
                f"\r\nPatched:\r\nSHA-1: {second.sha1}")
        row = {"patchhint": 3, "patchstatus": 1, "rominfo": info}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "one.zip"
            archive(path, {"patch.ips": IPS})
            matches, _ = _package_matches(row, path, bases)
            self.assertEqual([(base["sha1"], layout, evidence) for _, _, _, base, layout, evidence in matches],
                             [(first.sha1, "headered", "documented")])
            self.assertIsNone(bases.match(_documented_input(
                f"SHA1: {first.sha1}\nCRC32: {second.crc32}", "headerless",
            )))
            self.assertEqual(_package_matches({**row, "patchstatus": 4}, path, bases)[0], [])
            archive(path, {"patch.ips": IPS, "different.ips": IPS})
            self.assertEqual(_package_matches(row, path, bases)[0], [])

    def test_import_and_release_attachment(self):
        base = rom(1, "official")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            patches = root / "translations/snes/patches"
            patches.mkdir(parents=True)
            (scripts / "console.sql").write_text("INSERT INTO console (consolekey, consoleid) VALUES ('snes', 9);\n")
            (scripts / "language.sql").write_text("INSERT INTO language (id, name) VALUES (1, 'French'), (2, 'English');\n")
            (scripts / "patchstatus.sql").write_text("INSERT INTO patchstatus (id, description) VALUES (1, 'Fully Playable');\n")
            (scripts / "transauthor-project.sql").write_text(
                "INSERT INTO transauthor_project (project, person) VALUES (1, 7), (1, 8), (1, 8), (2, 7);\n"
            )
            (scripts / "transdata.sql").write_text(
                "INSERT INTO transdata (transkey, consolekey, patchfile, language, patchstatus, patchhint, "
                "patchver, patchrel_unix, rominfo) VALUES\n"
                f"(1, 9, '[1]test.zip', 1, 1, 4, '1.0', 200, 'SHA-1: {base.sha1}'),\n"
                f"(2, 9, '[2]test.zip', 2, 1, 4, 'Team''s v1', 100, 'CRC32 {base.crc32}');\n"
            )
            archive(patches / "[1]test.zip", {"French.ips": IPS})
            archive(patches / "[2]test.zip", {"English.ips": IPS})
            library = root / "library"
            reference = root / "authors.json"
            reference.write_text(json.dumps({
                "authors": {"7": "Translator", "8": "Editor"},
                "projectCredits": {
                    "1": {"version": "1.0", "releasedAt": 199, "authors": ["Earlier release team"]},
                    "2": {"version": "Team's v1", "releasedAt": 100, "authors": ["Local translator", "Local editor"]},
                },
            }))
            with patch("gamedb.catalog.snes_translations.AUTHOR_REFERENCE", reference):
                result = _import_translations(root, library, BaseRoms([base]))
            self.assertEqual(result["patches"], 2)
            self.assertEqual(result["withAuthors"], 2)
            self.assertEqual(len(list((library / "patches").iterdir())), 1)
            index = json.loads((library / INDEX_NAME).read_text())
            translations = index["translations"]
            self.assertEqual([record["language"] for record in translations], ["English", "French"])
            self.assertEqual(translations[0]["version"], "Team's v1")
            game = {"releases": [
                {"market": "JP", "status": "matched", "archives": [{"signature": "official"}]},
                {"market": "NA", "status": "matched", "archives": [{"signature": "different"}]},
                {"market": "PAL", "status": "ambiguous", "archives": [{"signature": "official"}]},
            ]}
            add_local_translations(game, library)
            selected, other_region, ambiguous = game["releases"]
            self.assertEqual([patch["language"] for patch in selected["translations"]], ["English", "French"])
            self.assertEqual([patch["authors"] for patch in selected["translations"]],
                             [["Local translator", "Local editor"], ["Translator", "Editor"]])
            self.assertEqual(selected["translations"][0]["baseReleaseSignature"], "official")
            self.assertEqual(selected["translations"][0]["baseSha1"], base.sha1)
            self.assertNotIn("translations", other_region)
            self.assertNotIn("translations", ambiguous)
            browse = [{"releases": [
                {"status": "matched", "archiveSignatures": ["official"]},
                {"status": "matched", "archiveSignatures": ["different"]},
                {"status": "ambiguous", "archiveSignatures": ["official"]},
            ]}]
            add_translation_availability(browse, library)
            self.assertEqual(browse[0]["releases"], [
                {"status": "matched", "hasTranslations": True},
                {"status": "matched", "hasTranslations": False},
                {"status": "ambiguous", "hasTranslations": False},
            ])
            record = translations[0]
            with _open_translation(library, _translation_location(library, record)) as stream:
                self.assertEqual(stream.read(), IPS)
            next((library / "patches").iterdir()).write_bytes(b"z" * len(IPS))
            with self.assertRaisesRegex(ValueError, "checksum changed"), _open_translation(
                library, _translation_location(library, record),
            ):
                self.fail("A changed translation file was opened")
            next((library / "patches").iterdir()).unlink()
            release = {"status": "matched", "archiveSignatures": ["official"]}
            add_translation_availability([{"releases": [release]}], library)
            self.assertFalse(release["hasTranslations"])
