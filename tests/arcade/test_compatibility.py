import unittest
from copy import deepcopy

from gamedb.arcade.compatibility import annotate_sources, game_fingerprint
from gamedb.arcade.resolver import Resolver
from tests.arcade.test_arcade import definition, file


def context(emulator, extra=False, member="data.bin"):
    machine = definition(description="Game")
    rom = {"name": "data.bin", "size": "10", "crc": "12345678"}
    if emulator == "MAME":
        rom["sha1"] = "a" * 40
    machine["rom"] = [rom]
    files = [dict(file("game", "a" * 40), member=member)]
    if extra:
        machine["rom"].append({"name": "extra.bin", "size": "10", "crc": "87654321"})
        files.append(dict(file("game", "b" * 40), member="extra.bin", crc="87654321"))
    definitions = {"game": machine}
    return {
        "emulator": emulator,
        "key": emulator + ":test",
        "version": "test",
        "digest": "digest",
        "definitions": definitions,
        "files": files,
        "plans": {"game": Resolver(definitions, files, emulator).resolve("game")},
    }


class CompatibilityTests(unittest.TestCase):
    def test_crc_dat_uses_inventory_sha1_and_both_cores_validate(self):
        mame, fbneo = context("MAME"), context("FBNeo")
        self.assertTrue(fbneo["plans"]["game"]["complete"])
        annotate_sources([mame, fbneo])
        self.assertEqual(fbneo["plans"]["game"]["identitySource"], "MAME:test")
        self.assertEqual(mame["plans"]["game"]["preferredCore"], "fbneo_libretro.so")
        self.assertEqual(len(mame["plans"]["game"]["compatibleEmulators"]), 2)

    def test_partial_overlap_is_not_identity_or_dual_compatibility(self):
        mame, fbneo = context("MAME"), context("FBNeo", extra=True)
        annotate_sources([mame, fbneo])
        self.assertEqual(fbneo["plans"]["game"]["identitySource"], "FBNeo:test")
        self.assertEqual(len(mame["plans"]["game"]["compatibleEmulators"]), 1)

    def test_different_member_layout_does_not_claim_both_cores(self):
        mame, fbneo = context("MAME", member="other.bin"), context("FBNeo")
        annotate_sources([mame, fbneo])
        self.assertEqual(len(mame["plans"]["game"]["compatibleEmulators"]), 1)

    def test_bios_only_overlap_is_not_game_identity(self):
        source = context("FBNeo")
        source["definitions"]["bios"] = definition(isbios="yes")
        source["definitions"]["bios"]["rom"] = deepcopy(
            source["definitions"]["game"]["rom"]
        )
        source["definitions"]["game"]["romof"] = "bios"
        self.assertIsNone(
            game_fingerprint(source["definitions"], "game", source["plans"]["game"])
        )

    def test_wrong_crc_does_not_resolve(self):
        source = context("FBNeo")
        source["files"][0]["crc"] = "ffffffff"
        self.assertFalse(
            Resolver(source["definitions"], source["files"], "FBNeo").resolve("game")[
                "complete"
            ]
        )
