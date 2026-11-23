from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
from shutil import which
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from gamedb.catalog.manuals import INDEX_NAME
from gamedb.explorer.manuals import warm_manual_cache
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

    @unittest.skipUnless(which("pdftoppm"), "requires Poppler")
    def test_manual_cover_renders_first_page_and_is_cached(self):
        source = self.root / "Manual.pdf"
        first = Image.new("RGB", (200, 300), "red")
        second = Image.new("RGB", (300, 200), "blue")
        first.save(source, save_all=True, append_images=[second])
        path = self.cache.get(source, 128)
        with Image.open(path) as preview:
            self.assertEqual((preview.format, preview.height), ("WEBP", 128))
            self.assertAlmostEqual(preview.width / preview.height, 2 / 3, delta=.01)
            red, _, blue = preview.getpixel((50, 50))
            self.assertGreater(red, 200)
            self.assertLess(blue, 30)
        with patch("gamedb.explorer.previews.subprocess.run") as render:
            self.assertEqual(self.cache.get(source, 128), path)
            render.assert_not_called()

    @unittest.skipUnless(which("pdftoppm") and which("pdfinfo"), "requires Poppler")
    def test_manual_reader_uses_the_requested_page_and_its_dimensions(self):
        source = self.root / "Booklet.pdf"
        first = Image.new("RGB", (200, 300), "red")
        second = Image.new("RGB", (400, 300), "blue")
        first.save(source, save_all=True, append_images=[second])
        revision = source.stat().st_mtime_ns
        self.assertEqual(self.cache.manual_pages(source, revision), ((200, 300), (400, 300)))
        size = self.cache.MANUAL_PAGE_SIZE
        cover = self.cache.get(source, size, page=1)
        inside = self.cache.get(source, size, page=2)
        self.assertNotEqual(cover, inside)
        with Image.open(inside) as page:
            self.assertEqual((page.format, page.size), ("WEBP", (1600, 1200)))
            red, _, blue = page.getpixel((50, 50))
            self.assertLess(red, 30)
            self.assertGreater(blue, 200)
        with patch("gamedb.explorer.previews.subprocess.run") as render:
            self.assertEqual(self.cache.get(source, size, page=2), inside)
            render.assert_not_called()

    def test_facing_pages_can_render_at_the_same_time(self):
        source = self.root / "Facing pages.pdf"
        source.touch()
        ready = threading.Barrier(2, timeout=3)

        def render(_source, _size, page):
            ready.wait()
            return Image.new("RGB", (20, 30), "red" if page == 1 else "blue")

        size = self.cache.MANUAL_PAGE_SIZE
        with patch("gamedb.explorer.previews._preview_source", side_effect=render) as render_page:
            with ThreadPoolExecutor(max_workers=2) as pool:
                pages = list(pool.map(lambda page: self.cache.get(source, size, page=page), (1, 2)))
            self.assertEqual(self.cache.get(source, size, page=2), pages[1])
            self.assertEqual(render_page.call_count, 2)
        self.assertNotEqual(*pages)
        self.assertTrue(all(path.is_file() for path in pages))

    @unittest.skipUnless(which("pdftoppm") and which("pdfinfo"), "requires Poppler")
    def test_manual_warming_populates_the_same_cover_and_page_paths_as_explorer(self):
        source = self.root / "Booklet.pdf"
        first = Image.new("RGB", (200, 300), "red")
        second = Image.new("RGB", (400, 300), "blue")
        first.save(source, save_all=True, append_images=[second])
        stat = source.stat()
        record = {"path": source.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        (self.root / INDEX_NAME).write_text(json.dumps({"version": 1, "manuals": {"manual": record}}))

        expected = {"manuals": 1, "covers": 1, "pages": 2, "failures": {}}
        self.assertEqual(warm_manual_cache(self.root, self.cache, workers=1), expected)
        reopened = ArtworkPreviewCache(self.root / "previews")
        with patch("gamedb.explorer.manuals.Popen") as batch, patch("gamedb.explorer.previews._preview_source") as render:
            cover = reopened.get(source, 320)
            page = reopened.get(source, reopened.MANUAL_PAGE_SIZE, page=2)
            self.assertEqual(warm_manual_cache(self.root, reopened, workers=1), expected)
            batch.assert_not_called()
            render.assert_not_called()
        with Image.open(cover) as image:
            self.assertEqual((image.format, image.height), ("WEBP", 320))
        with Image.open(page) as image:
            self.assertEqual((image.format, image.size), ("WEBP", (1600, 1200)))
            self.assertGreater(image.getpixel((50, 50))[2], 200)

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
                with patch("gamedb.explorer.server.mimetypes.guess_type", return_value=(None, None)):
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
