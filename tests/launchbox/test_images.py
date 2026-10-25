from email.message import Message
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from gamedb.catalog.launchbox_media import image_rank, IMAGE_KINDS
from gamedb.launchbox.image_cache import LaunchBoxImageCache, valid_filename

NAME = 'bdf75d60-7cfe-4c49-aa8d-719076752875.jpg'
JPEG = b'\xff\xd8\xff' + b'image bytes'


class Response(io.BytesIO):
    def __init__(self, content=JPEG, content_type='image/jpeg'):
        super().__init__(content)
        self.headers = Message()
        self.headers['Content-Type'] = content_type


class ImageCacheTests(unittest.TestCase):
    def test_fixed_origin_validated_filename_and_cached_second_request(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = LaunchBoxImageCache(directory)
            with patch('gamedb.launchbox.image_cache.urlopen', return_value=Response()) as fetch:
                path = cache.get(NAME, zlib.crc32(JPEG))
                self.assertEqual(path.read_bytes(), JPEG)
                self.assertEqual(cache.get(NAME, zlib.crc32(JPEG)), path)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(fetch.call_args.args[0].full_url, 'https://images.launchbox-app.com/' + NAME)

    def test_traversal_and_urls_never_reach_network(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('gamedb.launchbox.image_cache.urlopen') as fetch:
                for name in ['../' + NAME, 'https://evil.invalid/a.jpg', 'x.jpg?redirect=foo', NAME + '/a']:
                    self.assertFalse(valid_filename(name))
                    with self.assertRaises(ValueError):
                        LaunchBoxImageCache(directory).get(name)
                fetch.assert_not_called()

    def test_bad_checksum_html_and_partial_downloads_are_not_cached(self):
        for content, kind, checksum in [(JPEG, 'image/jpeg', 1), (b'<html>', 'text/html', None), (b'not an image', 'image/jpeg', None)]:
            with tempfile.TemporaryDirectory() as directory:
                with patch('gamedb.launchbox.image_cache.urlopen', return_value=Response(content, kind)):
                    with self.assertRaises(ValueError):
                        LaunchBoxImageCache(directory).get(NAME, checksum)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_download_size_is_bounded_and_failure_is_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = LaunchBoxImageCache(directory)
            with patch('gamedb.launchbox.image_cache.MAX_BYTES', 5), patch('gamedb.launchbox.image_cache.urlopen', return_value=Response()):
                with self.assertRaises(ValueError):
                    cache.get(NAME)
            self.assertEqual(list(Path(directory).iterdir()), [])
            with patch('gamedb.launchbox.image_cache.urlopen', return_value=Response()):
                self.assertEqual(cache.get(NAME).read_bytes(), JPEG)


class ArtworkSelectionTests(unittest.TestCase):
    def test_regions_use_catalog_codes(self):
        _, japan = image_rank('Japan', {'JP'}, NAME)
        _, europe = image_rank('Europe', {'JP'}, NAME)
        _, world = image_rank('World', {'JP'}, NAME)
        _, unknown = image_rank('', {'JP'}, NAME)
        self.assertGreater(japan, world)
        self.assertGreater(world, unknown)
        self.assertGreater(unknown, europe)
        self.assertEqual(image_rank('North America', {'US'}, NAME)[0], 'overlap')

    def test_no_fanart_or_back_covers_are_substituted(self):
        self.assertEqual(IMAGE_KINDS['Box - Front'], 'boxart')
        self.assertNotIn('Box - Back', IMAGE_KINDS)
        self.assertNotIn('Fanart - Background', IMAGE_KINDS)


if __name__ == '__main__':
    unittest.main()
