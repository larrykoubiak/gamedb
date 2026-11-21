"""Index and serve individual recordings from LHA and 7-Zip archives."""

import os
from contextlib import closing, contextmanager
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


def packed_locations(root, locations):
    """Read selected members from one archive in order, opening it once."""
    first = locations[0]
    path = location_path(root, first["source_path"])
    positions = {location["member_no"]: location for location in locations}
    with path.open("rb") as source:
        stat = os.fstat(source.fileno())
        if stat.st_mtime_ns != first["mtime_ns"] or stat.st_size != first["archive_size_bytes"]:
            raise ValueError("Soundtrack archive changed")
        try:
            with fd_reader(source.fileno(), format_name=ARCHIVE_FORMATS[first["archive_format"]]) as archive:
                for number, entry in enumerate(archive, 1):
                    location = positions.pop(number, None)
                    if location is None:
                        continue
                    expected_size = location["size_bytes"]
                    if (not entry.isfile or member_name(entry) != location["member_name"]
                            or entry.size != expected_size):
                        raise ValueError("Soundtrack archive member changed")
                    with SpooledTemporaryFile(max_size=1024 * 1024) as member:
                        for block in entry.get_blocks():
                            if member.tell() + len(block) > expected_size:
                                raise ValueError("Incorrect soundtrack archive member size")
                            member.write(block)
                        if member.tell() != expected_size:
                            raise ValueError("Incomplete soundtrack archive member")
                        member.seek(0)
                        yield location, member
                    if not positions:
                        return
        except ArchiveError as error:
            raise ValueError("Could not read the soundtrack archive member") from error
        raise ValueError("Soundtrack archive member unavailable")


@contextmanager
def open_vgm_location(root, location):
    if not location.get("archive_format") or not location["member_no"]:
        with open_location(root, location) as stream:
            yield stream
        return
    with closing(packed_locations(root, [location])) as members:
        _, stream = next(members)
        yield stream
