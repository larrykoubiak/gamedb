import struct
import tempfile
import unittest
from pathlib import Path

import msgpack

from gamedb.rdb.importer import (
    LibretroRdbImporter,
    json_value,
    normalized_hash,
    resolve_rdb_directory,
)
from gamedb.rdb.reader import RDB_MAGIC, RdbReader


class RdbReaderTests(unittest.TestCase):
    def test_streams_records_and_retains_binary_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Example.rdb"
            record = {
                "name": "Example",
                "size": 4,
                "crc": bytes.fromhex("1234abcd"),
                "sha1": bytes.fromhex("01" * 20),
            }
            payload = bytearray(struct.pack("8sQ", RDB_MAGIC, 0))
            payload.extend(msgpack.packb(record, use_bin_type=True))
            payload.extend(msgpack.packb(None, use_bin_type=True))
            payload.extend(msgpack.packb({"count": 1}, use_bin_type=True))
            path.write_bytes(payload)

            reader = RdbReader(path)
            rows = list(reader.records())

            self.assertEqual(rows, [record])
            self.assertEqual(reader.metadata, {"count": 1})

    def test_rejects_non_rdb_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.rdb"
            path.write_bytes(b"not an rdb")

            with self.assertRaisesRegex(ValueError, "header is truncated"):
                list(RdbReader(path).records())


class RdbImporterTests(unittest.TestCase):
    def test_resolves_checkout_and_detached_rdb_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "libretro-database"
            rdb = checkout / "rdb"
            rdb.mkdir(parents=True)
            (rdb / "Example.rdb").touch()

            self.assertEqual(resolve_rdb_directory(checkout), (checkout, rdb))
            self.assertEqual(resolve_rdb_directory(rdb), (rdb, rdb))

    def test_normalizes_binary_hashes_without_losing_raw_type(self):
        value = bytes.fromhex("ab" * 20)

        self.assertEqual(normalized_hash(value, 40), "ab" * 20)
        self.assertEqual(json_value(value), {"$binary_hex": "ab" * 20})

    def test_detached_import_requires_a_full_git_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            rdb = Path(directory)
            (rdb / "Example.rdb").touch()

            with self.assertRaisesRegex(ValueError, "40-character Git hash"):
                LibretroRdbImporter(object(), rdb, revision="main")

    def test_projects_common_identity_columns_from_raw_record(self):
        row = LibretroRdbImporter._entry_row(7, 3, {
            "name": "Example",
            "size": 1024,
            "crc": bytes.fromhex("1234abcd"),
            "serial": b"SLUS-12345",
            "developer": "Example Studio",
        })

        self.assertEqual(row["crc_hex"], "1234abcd")
        self.assertEqual(row["serial"], "SLUS-12345")
        self.assertEqual(row["raw_record"]["developer"], "Example Studio")


if __name__ == "__main__":
    unittest.main()
