"""Create browser-playable FLAC copies of supported soundtrack formats."""

import os
from shutil import copyfileobj
import subprocess
from tempfile import NamedTemporaryFile
from threading import BoundedSemaphore, Lock

from gamedb.vgm.archives import open_vgm_location


_conversions = BoundedSemaphore(2)
_locks = [Lock() for _ in range(32)]
INPUT_FORMATS = {"ape": "ape", **dict.fromkeys(("aif", "aiff", "aifc"), "aiff")}


def browser_flac(cache, root, key, location):
    if location["kind"] != "track" or (format_name := INPUT_FORMATS.get(location["format"])) is None:
        raise ValueError("Unsupported soundtrack format for FLAC playback")
    directory = cache / "soundtrack-flac" / key[:2]
    target = directory / f"{key}-{location['mtime_ns']}.flac"
    with _locks[int(key[:2], 16) % len(_locks)]:
        if target.is_file():
            return target
        directory.mkdir(parents=True, exist_ok=True)
        with _conversions, NamedTemporaryFile(dir=directory) as original, NamedTemporaryFile(dir=directory) as output:
            with open_vgm_location(root, location) as source:
                copyfileobj(source, original, 1024 * 1024)
            original.flush()
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-threads", "1", "-protocol_whitelist", "file",
                "-f", format_name, "-i", original.name, "-map", "0:a:0", "-map_metadata", "-1",
                "-c:a", "flac", "-compression_level", "2", "-threads", "1", "-f", "flac", output.name,
            ], check=True, capture_output=True, timeout=90)
            if not os.path.getsize(output.name):
                raise ValueError("Soundtrack conversion produced no audio")
            try:
                os.link(output.name, target)
            except FileExistsError:
                pass
    return target
