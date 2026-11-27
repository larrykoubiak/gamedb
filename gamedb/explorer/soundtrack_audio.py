"""Create browser-playable FLAC copies of supported soundtrack formats."""

import os
from pathlib import Path
from shutil import copyfileobj, which
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import BoundedSemaphore, Lock

from gamedb.vgm.archives import open_vgm_location
from gamedb.vgm.inventory import HANDHELD_STREAMS


_conversions = BoundedSemaphore(2)
_locks = [Lock() for _ in range(32)]
INPUT_FORMATS = {"ape": "ape", "mpg": "mpeg", **dict.fromkeys(("aif", "aiff", "aifc"), "aiff")}
STREAM_FORMATS = frozenset({"adp", "ads", "afc", "aix", "ast", "at3", "brstm", "dsp", "grn", "ss2", "vag", "xa"}
                           | {suffix[1:] for suffix in HANDHELD_STREAMS})


def flac_formats():
    return set(INPUT_FORMATS) | (STREAM_FORMATS if which("vgmstream-cli") else set())


def _transcode(source, output, input_format):
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-threads", "1", "-protocol_whitelist", "file",
        "-f", input_format, "-i", str(source), "-map", "0:a:0", "-map_metadata", "-1",
        "-c:a", "flac", "-compression_level", "2", "-threads", "1", "-f", "flac", str(output),
    ], check=True, capture_output=True, timeout=90)


def browser_flac(cache, root, key, location):
    format_name = location["format"]
    if location["kind"] != "track" or format_name not in flac_formats():
        raise ValueError("Unsupported soundtrack format for FLAC playback")
    directory = cache / "soundtrack-flac" / key[:2]
    target = directory / f"{key}-{location['mtime_ns']}.flac"
    with _locks[int(key[:2], 16) % len(_locks)]:
        if target.is_file():
            return target
        directory.mkdir(parents=True, exist_ok=True)
        with _conversions, TemporaryDirectory(dir=directory) as work, NamedTemporaryFile(dir=directory) as output:
            original = Path(work) / f"track.{format_name}"
            with open_vgm_location(root, location) as source, original.open("wb") as destination:
                copyfileobj(source, destination, 1024 * 1024)
            if format_name in STREAM_FORMATS:
                wave = Path(work) / "decoded.wav"
                if options := location.get("streamOptions"):
                    playlist = original.with_suffix(".txtp")
                    playlist.write_text(original.name + options + "\n", encoding="ascii")
                    original = playlist
                subprocess.run(["vgmstream-cli", "-i", "-o", str(wave), str(original)],
                               check=True, capture_output=True, timeout=90)
                _transcode(wave, output.name, "wav")
            else:
                _transcode(original, output.name, INPUT_FORMATS[format_name])
            if not os.path.getsize(output.name):
                raise ValueError("Soundtrack conversion produced no audio")
            try:
                os.link(output.name, target)
            except FileExistsError:
                pass
    return target
