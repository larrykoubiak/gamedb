from base64 import b64encode
from contextlib import closing
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import Mock
from urllib.parse import urlencode
from zipfile import ZipFile

from gamedb.catalog.translations import DISC_LAYOUT, INDEX_NAME, INDEX_VERSION
from gamedb.explorer.related_media import add_local_translations
from gamedb.explorer.server import ExplorerHandler


class QuietHandler(ExplorerHandler):
    def log_message(self, *args):
        pass


class DiscDownloadTests(unittest.TestCase):
    def test_disc_download_requires_authorization_and_a_published_release(self):
        signature, key, password = "a" * 32, "b" * 64, "c" * 43
        url = f"/api/v1/releases/{signature}/translations/{key}/download"
        with TemporaryDirectory() as directory, ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler) as server:
            root = Path(directory)
            artifact = root / "build.zip"
            with ZipFile(artifact, "w") as archive:
                archive.writestr("Game.cue", 'FILE "Game.bin" BINARY\n')
            digest = sha256(artifact.read_bytes()).hexdigest()
            (root / "discs").mkdir()
            artifact = artifact.rename(root / "discs" / f"{digest}.zip")
            size = artifact.stat().st_size
            patch = b"patch"
            patch_digest = sha256(patch).hexdigest()
            (root / "patches").mkdir()
            (root / "patches" / f"{patch_digest}.zip").write_bytes(patch)
            entry = {
                "key": key, "signatures": [signature], "sha256": patch_digest, "format": "zip", "size": len(patch),
                "layout": DISC_LAYOUT, "language": "English", "version": "1.0", "title": "Test",
                "releasedAt": 1, "filename": "Patch.zip",
                "discSet": {"filename": "Game [English].zip", "sha256": digest, "size": size,
                            "mtimeNs": artifact.stat().st_mtime_ns},
            }
            patch_only = dict(entry, key="d" * 64, discSet=None)
            (root / INDEX_NAME).write_text(json.dumps({"version": INDEX_VERSION, "translations": [entry, patch_only]}))
            release = {"status": "matched", "archives": [{"signature": signature}]}
            add_local_translations({"releases": [release]}, root, "playstation")
            translations = {item["key"]: item for item in release["translations"]}
            self.assertEqual(translations[key]["romDownloadUrl"], url)
            self.assertEqual(translations[key]["discDownloadSha256"], digest)
            self.assertEqual(translations[key]["discLaunchPath"], "Game.cue")
            self.assertNotIn("romDownloadUrl", translations[patch_only["key"]])
            server.repository = Mock()
            server.repository.retail_has_archive.return_value = True
            server.retail_translation_roots = {"playstation": root}
            server.api_key = password
            thread = Thread(target=server.serve_forever)
            thread.start()

            def request(method, headers=None, body=None):
                with closing(HTTPConnection(*server.server_address, timeout=5)) as client:
                    client.request(method, url, headers=headers or {}, body=body)
                    response = client.getresponse()
                    return response.status, response.headers, response.read()

            try:
                self.assertEqual(request("GET")[0], 401)
                self.assertEqual(request("POST", {"Content-Type": "application/x-www-form-urlencoded"},
                                         "key=wrong")[0], 401)
                self.assertEqual(request("POST")[0], 400)
                server.repository.retail_has_archive.assert_not_called()
                bearer = {"Authorization": f"Bearer {password}"}
                status, headers, body = request("HEAD", bearer)
                self.assertEqual((status, int(headers["Content-Length"]), body), (200, size, b""))
                self.assertEqual(headers["Cache-Control"], "private, no-store")
                self.assertIn("Game%20%5BEnglish%5D.zip", headers["Content-Disposition"])
                expected_digest = f"sha-256=:{b64encode(bytes.fromhex(digest)).decode('ascii')}:"
                self.assertEqual(headers["Repr-Digest"], expected_digest)
                status, headers, body = request("GET", {**bearer, "Range": "bytes=0-3"})
                self.assertEqual((status, headers["Content-Range"], body), (206, f"bytes 0-3/{size}", b"PK\x03\x04"))
                self.assertEqual(headers["Repr-Digest"], expected_digest)
                status, _, body = request("POST", {"Content-Type": "application/x-www-form-urlencoded"},
                                          urlencode({"key": password}))
                self.assertEqual((status, body), (200, artifact.read_bytes()))

                server.repository.retail_has_archive.return_value = False
                self.assertEqual(request("GET", bearer)[0], 404)
            finally:
                server.shutdown()
                thread.join()
