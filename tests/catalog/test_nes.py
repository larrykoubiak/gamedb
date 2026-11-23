from hashlib import md5, sha1, sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from zipfile import ZipFile
from zlib import crc32

from gamedb.catalog.nes_media import add_manuals
from gamedb.catalog.nes_rom import ines_boundaries
from gamedb.catalog.patching import PatchError, apply_translation
from gamedb.catalog.retail import match_archives
from gamedb.catalog.translations import BaseRoms, NES_LAYOUTS, _package_matches


HEADER = b"NES\x1a\x01" + bytes(11)
PAYLOAD = bytes(16 * 1024)
IPS = b"PATCH\x00\x00\x10\x00\x01XEOF"


def checksums(data):
    return {"sha1": sha1(data).hexdigest(), "md5": md5(data).hexdigest(),
            "crc32": f"{crc32(data):08x}", "size": len(data)}


def release(edition, market, title):
    return {"key": f"{market}-{edition}", "edition": edition, "market": market,
            "titles": [title], "channel": "cartridge"}


class NesTests(unittest.TestCase):
    def test_layout_distinguishes_trainer_and_nes2_exponent_encoding(self):
        header = bytearray(HEADER)
        header[6] = 4
        self.assertEqual(ines_boundaries(header + bytes(512) + PAYLOAD), (528, 16912, 16912))
        header[4], header[6], header[7], header[9] = 14 << 2, 0, 8, 15
        self.assertEqual(ines_boundaries(header + PAYLOAD), (16, 16400, 16400))

    def test_ips_with_a_body_hash_needs_layout_evidence(self):
        rom = SimpleNamespace(signature="nes", **checksums(HEADER + PAYLOAD))
        bases = BaseRoms([rom], ines_fingerprints={rom.sha1: {"withoutHeader": checksums(PAYLOAD)}})
        claims = f"ROM SHA-1: {sha1(PAYLOAD).hexdigest()}"
        row = {"patchhint": 1, "patchstatus": 1, "rominfo": f"File SHA-1: {'a' * 40}\n{claims}"}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "translation.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("translation.ips", IPS)
            matches, reason = _package_matches(row, path, bases, layouts=NES_LAYOUTS, native_layout="ines")
            self.assertIsNone(reason)
            self.assertEqual(matches[0][4], "ines-unconfirmed")
            row["rominfo"] = f"File SHA-1: {rom.sha1}\n{claims}"
            matches, _ = _package_matches(row, path, bases, layouts=NES_LAYOUTS, native_layout="ines")
            self.assertEqual(matches[0][4], "ines")

    def test_nes_patch_output_checks_header_and_payload_size(self):
        image = HEADER + PAYLOAD
        checked = b"UPS1\x00\xff\x00\xff\x80X\x00"
        changed = b"X" + PAYLOAD[1:]
        checked += crc32(PAYLOAD).to_bytes(4, "little") + crc32(changed).to_bytes(4, "little")
        checked += crc32(checked).to_bytes(4, "little")
        self.assertEqual(apply_translation(image, checked, "ups", "ines-payload"), HEADER + changed)
        alternate = HEADER[:6] + b"\x01" + HEADER[7:]
        self.assertEqual(apply_translation(image, IPS, "ips", "ines", output_header=alternate), alternate + changed)
        with self.assertRaisesRegex(PatchError, "image size do not agree"):
            apply_translation(image, b"PATCH\x00\x40\x10\x00\x01XEOF", "ips", "ines")
        with self.assertRaisesRegex(PatchError, "Invalid iNES"):
            apply_translation(image, IPS, "ips", "ines", output_header=bytes(16))

    def test_reviewed_standalone_ips_can_override_legacy_project_flags(self):
        image = HEADER + PAYLOAD
        base = SimpleNamespace(signature="nes", **checksums(image))
        bases = BaseRoms([base])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "translation.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("translation.ips", IPS)
                archive.writestr("optional.ips", IPS)
            review = {
                "archive": path.name, "baseSha1": base.sha1, "layout": "ines",
                "standalone": True, "patches": {"translation.ips": sha256(IPS).hexdigest()},
                "outputSha1": {"translation.ips": sha1(HEADER + b"X" + PAYLOAD[1:]).hexdigest()},
            }
            for hint, status in ((12, 1), (1, 4)):
                with self.subTest(hint=hint, status=status):
                    row = {"patchhint": hint, "patchstatus": status, "rominfo": f"SHA-1: {base.sha1}"}
                    options = {"layouts": NES_LAYOUTS, "native_layout": "ines"}
                    self.assertEqual(_package_matches(row, path, bases, **options)[0], [])
                    incomplete = {**review, "outputSha1": {}}
                    self.assertEqual(_package_matches(row, path, bases, review=incomplete, **options)[0], [])
                    matches, reason = _package_matches(row, path, bases, review=review, **options)
                    self.assertIsNone(reason)
                    self.assertEqual([(name, layout, evidence) for name, _, _, _, layout, evidence in matches],
                                     [("translation.ips", "ines", "reviewed")])

    def test_independent_archive_does_not_claim_a_same_name_licensed_edition(self):
        licensed = release("Example", "NA", "Example")
        independent = release("Example (Publisher)", "NA", "Example (Publisher)")
        catalog = {"games": [{"releases": [licensed]}, {"releases": [independent]}]}
        archives = [{"title": "Example", "regions": ["US"], "channel": "cartridge", "signature": signature,
                     "archiveNames": [signature + ".zip"], "softwareKey": signature}
                    for signature in ("1" * 32, "2" * 32)]
        match_archives(catalog, archives, [], [
            {"edition": independent["edition"], "market": "NA", "signature": "2" * 32,
             "independentRetail": True, "evidence": "Regional retail box and cartridge chips"},
        ])
        self.assertEqual([a["signature"] for a in licensed["archives"]], ["1" * 32])
        self.assertEqual([a["signature"] for a in independent["archives"]], ["2" * 32])

    def test_manual_needs_unambiguous_region_and_title(self):
        jp = release("Example", "JP", "Example")
        na = release("Example", "NA", "Example")
        catalog = {"games": [{"title": "Example", "releases": [jp, na]}]}
        file = {"name": "Example.pdf", "size": "120", "sha1": "1" * 40}
        add_manuals(catalog, [("Example", None, ["eng"], file), ("Example", "JP", ["jpn"], file)])
        self.assertNotIn("manuals", na)
        self.assertEqual(jp["manuals"][0]["language"], "Japanese")
