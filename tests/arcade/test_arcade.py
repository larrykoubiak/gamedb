import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from gamedb.arcade.bundle import prepare_manifest, public_manifest, write_bundle
from gamedb.arcade.importer import validate_graph
from gamedb.arcade.resolver import Resolver, install_signature, safe_path


def definition(**values):
    return dict(
        rom=[], disk=[], device_ref=[], sample=[], driver=[{"status": "good"}], **values
    )


def file(set_name, sha, kind="rom", **values):
    return dict(
        id=1,
        package_id=1,
        archive_name=set_name + ".zip",
        set_name=set_name,
        kind=kind,
        sha1=sha,
        disk_sha1="disk-content",
        size=10,
        crc="12345678",
        path="/roms/" + set_name + ".zip",
        member="data.bin",
        **values,
    )


class ResolverTests(unittest.TestCase):
    def test_split_clone_includes_parent_bios_and_rom_device(self):
        machines = {
            "parent": definition(),
            "bios": definition(),
            "device": definition(),
            "clone": definition(cloneof="parent", romof="parent"),
        }
        machines["parent"]["romof"] = "bios"
        machines["clone"]["rom"] = [
            {"name": "own", "sha1": "own", "size": "10"},
            {"name": "shared", "sha1": "shared", "size": "10"},
            {"name": "bios", "sha1": "bios", "size": "10"},
        ]
        machines["clone"]["device_ref"] = [{"name": "device"}]
        machines["device"]["rom"] = [
            {"name": "firmware", "sha1": "firmware", "size": "10"}
        ]
        plan = Resolver(
            machines,
            [
                file("clone", "own"),
                file("parent", "shared"),
                file("bios", "bios"),
                file("device", "firmware"),
            ],
        ).resolve("clone")
        self.assertTrue(plan["complete"])
        self.assertEqual(plan["family"], "parent")
        self.assertEqual(
            {a["installPath"] for a in plan["assets"]},
            {"clone.zip", "parent.zip", "bios.zip", "device.zip"},
        )

    def test_merged_chd_selects_only_variant_disk_and_uses_content_hash(self):
        machines = {
            "parent": definition(),
            "clone": definition(cloneof="parent", romof="parent"),
        }
        machines["clone"]["disk"] = [{"name": "revision2", "sha1": "disk-content"}]
        disk = file("parent", "physical-file-hash", "disk")
        disk.update(path="/roms/parent", member="revision2.chd")
        sibling = dict(disk, disk_sha1="other-content", member="revision1.chd")
        plan = Resolver(machines, [disk, sibling]).resolve("clone")
        self.assertTrue(plan["complete"])
        self.assertEqual(
            [a["installPath"] for a in plan["assets"]],
            ["clone.zip", "clone/revision2.chd"],
        )
        self.assertEqual(plan["assets"][1]["sha1"], "physical-file-hash")

    def test_unknown_hash_and_samples_are_not_silently_complete(self):
        machine = definition()
        machine["rom"] = [{"name": "missing", "status": "nodump"}]
        machine["sample"] = [{"name": "sound"}]
        plan = Resolver({"game": machine}, []).resolve("game")
        self.assertFalse(plan["complete"])
        self.assertEqual(
            {m["reason"] for m in plan["missing"]},
            {"undumped", "missing_sample_inventory"},
        )

    def test_matching_content_in_an_unrelated_set_is_not_a_dependency(self):
        machine = definition()
        machine["rom"] = [{"name": "data", "sha1": "same", "size": "10"}]
        self.assertFalse(
            Resolver({"game": machine}, [file("unrelated", "same")]).resolve("game")[
                "complete"
            ]
        )

    def test_cycles_and_dangling_references_are_rejected(self):
        for machines in (
            {"a": definition(cloneof="a")},
            {"a": definition(romof="missing")},
        ):
            with self.assertRaises(ValueError):
                validate_graph(machines)

    def test_versioned_machine_signature_does_not_merge_identical_variants(self):
        self.assertNotEqual(
            install_signature("MAME:1", "a", []), install_signature("MAME:1", "b", [])
        )
        self.assertNotEqual(
            install_signature("MAME:1", "a", []), install_signature("MAME:2", "a", [])
        )

    def test_install_paths_reject_traversal(self):
        for value in ("../evil", "/absolute", "a/../b", "C:/disk", "a\\b", "a//b"):
            with self.assertRaises(ValueError):
                safe_path(value)


class BundleTests(unittest.TestCase):
    def test_bundle_preserves_zip_and_chd_layout_without_exposing_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rom = root / "parent.zip"
            disk = root / "disk.chd"
            with zipfile.ZipFile(rom, "w") as archive:
                archive.writestr("data.bin", b"rom")
            with zipfile.ZipFile(rom) as archive:
                crc = archive.getinfo("data.bin").CRC
            disk.write_bytes(b"chd")
            source = {
                "releaseSignature": "a" * 32,
                "plan": {
                    "shortname": "clone",
                    "family": "parent",
                    "emulationStatus": "good",
                    "launchPath": "clone.zip",
                    "missing": [],
                    "assets": [
                        {
                            "kind": "rom",
                            "installPath": "parent.zip",
                            "resolvedPath": str(rom),
                            "requiredMembers": [
                                {"name": "data.bin", "size": 3, "crc": f"{crc:08x}"}
                            ],
                        },
                        {
                            "kind": "disk",
                            "installPath": "clone/rev2.chd",
                            "resolvedPath": str(disk),
                            "size": 3,
                            "requiredMembers": [],
                        },
                        {
                            "kind": "launch",
                            "installPath": "clone.zip",
                            "requiredMembers": [],
                        },
                    ],
                },
            }
            manifest = prepare_manifest(source, root)
            self.assertTrue(manifest["complete"])
            self.assertNotIn(directory, json.dumps(public_manifest(manifest)))
            output = io.BytesIO()
            write_bundle(output, manifest)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("roms/clone/rev2.chd"), b"chd")
                self.assertEqual(archive.read("roms/parent.zip"), rom.read_bytes())
                with zipfile.ZipFile(
                    io.BytesIO(archive.read("roms/clone.zip"))
                ) as launch:
                    self.assertEqual(launch.namelist(), [])
            disk.unlink()
            incomplete = prepare_manifest(source, root)
            self.assertFalse(incomplete["complete"])
            with self.assertRaises(ValueError):
                write_bundle(io.BytesIO(), incomplete)

    def test_source_path_escape_is_reported_as_incomplete(self):
        source = {
            "releaseSignature": "a" * 32,
            "plan": {
                "shortname": "game",
                "family": "game",
                "emulationStatus": "good",
                "launchPath": "game.zip",
                "missing": [],
                "assets": [
                    {
                        "kind": "disk",
                        "installPath": "game/disk.chd",
                        "resolvedPath": "/etc/passwd",
                        "size": 0,
                        "requiredMembers": [],
                    }
                ],
            },
        }
        self.assertFalse(prepare_manifest(source, Path("/roms"))["complete"])


class ApiTests(unittest.TestCase):
    def test_authenticated_manifest_and_incomplete_bundle(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from types import SimpleNamespace
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        from gamedb.explorer.server import ExplorerHandler

        signature = "b" * 32
        source = {
            "schemaVersion": 2,
            "kind": "arcade",
            "releaseSignature": signature,
            "plan": {
                "shortname": "game",
                "family": "game",
                "emulationStatus": "good",
                "launchPath": "game.zip",
                "assets": [],
                "missing": [{"kind": "disk", "reason": "missing_inventory"}],
            },
        }

        class QuietHandler(ExplorerHandler):
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        server.api_key = "test-key"
        server.rom_root = Path("/roms")
        server.repository = SimpleNamespace(
            arcade_install_manifest=lambda value: source if value == signature else None
        )
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/api/v1/releases/{signature}"
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/install-manifest")
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
            headers = {"Authorization": "Bearer test-key"}
            with urlopen(
                Request(base + "/install-manifest", headers=headers)
            ) as response:
                body = json.load(response)
                self.assertEqual(body["schemaVersion"], 2)
                self.assertFalse(body["complete"])
                self.assertIsNone(body["bundleUrl"])
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/install-bundle", headers=headers))
            self.assertEqual(error.exception.code, 409)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
