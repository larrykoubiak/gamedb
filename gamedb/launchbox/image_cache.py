"""Fetch approved LaunchBox image filenames from a fixed origin into a local cache."""
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.request import Request, urlopen
import zlib

ORIGIN = 'https://images.launchbox-app.com/'
FILENAME = re.compile(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\.(?:png|jpg|jpeg)', re.I)
MAX_BYTES = 32 * 1024 * 1024


def valid_filename(filename):
    return bool(FILENAME.fullmatch(filename))


class LaunchBoxImageCache:
    def __init__(self, root):
        self.root = Path(root)
        self.locks = [threading.Lock() for _ in range(64)]

    def get(self, filename, crc32=None):
        if not valid_filename(filename):
            raise ValueError('Invalid LaunchBox image filename')
        with self.locks[hash(filename) % len(self.locks)]:
            path = self.root / filename
            if path.is_file():
                return path
            self.root.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(dir=self.root, prefix='.download-')
            try:
                request = Request(ORIGIN + filename, headers={'User-Agent': 'GameDB/1.0'})
                with os.fdopen(descriptor, 'wb') as target, urlopen(request, timeout=30) as response:
                    if response.headers.get_content_type() not in {'image/png', 'image/jpeg'}:
                        raise ValueError('LaunchBox returned a non-image response')
                    size = 0
                    checksum = 0
                    signature = b''
                    while block := response.read(64 * 1024):
                        if not signature:
                            signature = block[:8]
                        size += len(block)
                        if size > MAX_BYTES:
                            raise ValueError('LaunchBox image exceeds download limit')
                        checksum = zlib.crc32(block, checksum)
                        target.write(block)
                    if not (signature.startswith(b'\xff\xd8\xff') or signature == b'\x89PNG\r\n\x1a\n'):
                        raise ValueError('Invalid LaunchBox image bytes')
                    if crc32 is not None and checksum != int(crc32):
                        raise ValueError('LaunchBox image checksum differs from imported reference')
                os.replace(temporary, path)
                return path
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
