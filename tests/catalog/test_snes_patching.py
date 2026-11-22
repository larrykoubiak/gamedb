import unittest
from zlib import crc32

from gamedb.catalog.snes_patching import PatchError, apply_translation, embedded_input, valid_ips


def with_checksums(body, original, patched):
    body += crc32(original).to_bytes(4, "little") + crc32(patched).to_bytes(4, "little")
    return body + crc32(body).to_bytes(4, "little")


class SnesPatchingTests(unittest.TestCase):
    def test_headered_ips_uses_shifted_offsets_and_returns_a_headerless_rom(self):
        patch = b"PATCH\x00\x02\x01\x00\x01X\x00\x02\x05\x00\x00\x00\x03YEOF\x00\x02\x07"
        original = bytearray(b"abcd")
        self.assertEqual(apply_translation(original, patch, "ips", "headered"), b"aXcd\x00YY")
        self.assertEqual(original, b"abcd")
        self.assertTrue(valid_ips(patch))
        self.assertFalse(valid_ips(patch[:-1]))

    def test_invalid_ips_and_unsupported_input_layout_are_rejected(self):
        patch = b"PATCH\xff\xff\xff\x00\x02\x00\x00EOF"
        with self.assertRaisesRegex(PatchError, "exceed 16 MiB"):
            apply_translation(b"ab", patch, "ips", "headerless")
        with self.assertRaisesRegex(PatchError, "unsupported input layout"):
            apply_translation(b"ab", patch, "ips", "interleaved")

    def test_bps_copy_actions_and_checksums(self):
        original = b"0123456789"
        patched = b"01XY345" + b"454545454"
        body = b"BPS1\x8a\x90\x80\x84\x85XY\x8a\x86\xa3\x8a"
        patch = with_checksums(body, original, patched)
        self.assertEqual(embedded_input(patch, "bps"), (len(original), f"{crc32(original):08x}"))
        self.assertEqual(apply_translation(original, patch, "bps", "headerless"), patched)
        with self.assertRaisesRegex(PatchError, "different base ROM"):
            apply_translation(b"1234567890", patch, "bps", "headerless")
        bad_target = with_checksums(body, original, b"!" * len(patched))
        with self.assertRaisesRegex(PatchError, "patched ROM checksum"):
            apply_translation(original, bad_target, "bps", "headerless")

    def test_ups_applies_relative_xor_edits_when_shrinking_or_expanding(self):
        original, patched = b"abcdef", b"aXcdY"
        body = b"UPS1\x86\x85" + bytes((0x81, ord("b") ^ ord("X"), 0, 0x81, ord("e") ^ ord("Y"), ord("f"), 0))
        patch = with_checksums(body, original, patched)
        self.assertEqual(apply_translation(original, patch, "ups", "headerless"), patched)

        original, patched = b"A", b"A\0Z"
        patch = with_checksums(b"UPS1\x81\x83\x82Z\0", original, patched)
        self.assertEqual(apply_translation(original, patch, "ups", "headerless"), patched)
        corrupt = patch[:-1] + bytes((patch[-1] ^ 1,))
        with self.assertRaisesRegex(PatchError, "patch checksum"):
            apply_translation(original, corrupt, "ups", "headerless")
