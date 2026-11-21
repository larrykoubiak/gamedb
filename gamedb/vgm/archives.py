"""Index and serve individual recordings from LHA and 7-Zip archives."""

import os
from contextlib import contextmanager
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile

from libarchive import fd_reader, file_reader
from libarchive.exception import ArchiveError

from gamedb.exo.media import location_path, open_location


ARCHIVE_FORMATS = {"7z": "7zip", "lha": "lha"}


def member_name(entry):
    name = entry.pathname
    if isinstance(name, bytes):
        return name.decode("cp1252", errors="replace")
    return name or ""


def safe_member(path):
    name = PurePosixPath(path)
    return bool(name.parts) and not name.is_absolute() and all(
        part != ".." and not part.startswith((".", "@")) for part in name.parts
    )


def members(path, format_name):
    with file_reader(str(path), format_name=ARCHIVE_FORMATS[format_name]) as archive:
        for number, entry in enumerate(archive, 1):
            name = member_name(entry)
            if entry.isfile and entry.size and entry.size > 0 and safe_member(name):
                yield number, name, entry.size


@contextmanager
def open_vgm_location(root, location):
    format_name = location.get("archive_format")
    if not format_name or not location["member_no"]:
        with open_location(root, location) as stream:
            yield stream
        return

    path = location_path(root, location["source_path"])
    expected_size = location["size_bytes"]
    with path.open("rb") as source, SpooledTemporaryFile(max_size=1024 * 1024) as member:
        stat = os.fstat(source.fileno())
        if stat.st_mtime_ns != location["mtime_ns"] or stat.st_size != location["archive_size_bytes"]:
            raise ValueError("Soundtrack archive changed")
        try:
            with fd_reader(source.fileno(), format_name=ARCHIVE_FORMATS[format_name]) as archive:
                for number, entry in enumerate(archive, 1):
                    if number != location["member_no"]:
                        continue
                    if (not entry.isfile or member_name(entry) != location["member_name"]
                            or entry.size != expected_size):
                        raise ValueError("Soundtrack archive member changed")
                    for block in entry.get_blocks():
                        if member.tell() + len(block) > expected_size:
                            raise ValueError("Incorrect soundtrack archive member size")
                        member.write(block)
                    break
                else:
                    raise ValueError("Soundtrack archive member unavailable")
        except ArchiveError as error:
            raise ValueError("Could not read the soundtrack archive member") from error
        if member.tell() != expected_size:
            raise ValueError("Incomplete soundtrack archive member")
        member.seek(0)
        yield member
