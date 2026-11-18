from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from gamedb.explorer.previews import ArtworkPreviewCache
from gamedb.explorer.server import ExplorerHandler


class PreviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "Box art.png"
        Image.new("RGBA", (600, 300), (20, 40, 60, 120)).save(self.source)
        self.cache = ArtworkPreviewCache(self.root / "previews")

    def test_concurrent_requests_and_restarts_reuse_the_same_webp(self):
        with patch.object(Image, "open", wraps=Image.open) as opened:
            with ThreadPoolExecutor(max_workers=5) as pool:
                paths = list(pool.map(lambda _: self.cache.get(self.source, 320), range(8)))
            reopened = ArtworkPreviewCache(self.root / "previews")
            self.assertEqual(reopened.get(self.source, 320), paths[0])
            opened.assert_called_once()
        self.assertEqual(len(set(paths)), 1)
        with Image.open(paths[0]) as preview:
            self.assertEqual((preview.format, preview.size, preview.mode), ("WEBP", (320, 160), "RGBA"))
            self.assertEqual(preview.getpixel((0, 0))[3], 120)
        with Image.open(self.cache.get(self.source, 128)) as small:
            self.assertEqual(small.size, (128, 64))
        Image.new("RGB", (20, 30), "blue").save(self.source)
        changed = reopened.get(self.source, 320)
        self.assertNotEqual(changed, paths[0])
        with Image.open(changed) as updated:
            self.assertEqual(updated.size, (20, 30))

    def test_http_previews_revalidate_and_originals_remain_zoomable(self):
        class QuietHandler(ExplorerHandler):
            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler) as server:
            server.thumbnail_root = self.root
            server.preview_cache = self.cache
            server.repository = Mock()
            server.repository.launchbox_image.return_value = None
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                def get(path, headers=None):
                    client = HTTPConnection(*server.server_address)
                    try:
                        client.request("GET", path, headers=headers or {})
                        response = client.getresponse()
                        return response.status, response.headers, response.read()
                    finally:
                        client.close()

                path = "/previews/320/Box%20art.png"
                status, headers, body = get(path)
                self.assertEqual((status, headers["Content-Type"]), (200, "image/webp"))
                with Image.open(BytesIO(body)) as cover:
                    self.assertEqual(cover.size, (320, 160))
                status, cached_headers, body = get(path, {"If-None-Match": headers["ETag"]})
                self.assertEqual(status, 304)
                self.assertEqual(cached_headers["ETag"], headers["ETag"])
                self.assertEqual(body, b"")
                self.assertEqual(get("/media/Box%20art.png")[2], self.source.read_bytes())
                for missing in ("/previews/321/Box%20art.png", "/previews/128/missing.png",
                                "/previews/128/%2e%2e/outside.png",
                                "/previews/320/launchbox/logo/12345678-abcd-abcd-abcd-123456789abc.png"):
                    self.assertEqual(get(missing)[0], 404)
                self.source.write_bytes(b"cannot decode")
                status, headers, _ = get(path)
                self.assertEqual((status, headers["Location"]), (307, "/media/Box%20art.png"))
                self.assertEqual(headers["Cache-Control"], "no-store")
                Image.new("RGB", (40, 30)).save(self.source)
                self.assertEqual(get(path)[0], 200)
            finally:
                server.shutdown()
