"""Access a catalogued file or exact ZIP member on the read-only eXo mount."""

import os
from contextlib import contextmanager
from zipfile import ZipFile


def location_path(root, relative):
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Invalid media location")
    return path


@contextmanager
def open_location(root, location):
    path = location_path(root, location["source_path"])
    if location["member_no"]:
        with ZipFile(path) as archive:
            index = location["member_no"] - 1
            members = archive.infolist()
            if not 0 <= index < len(members):
                raise ValueError("Media archive changed")
            member = members[index]
            if (
                member.filename != location["member_name"]
                or member.file_size != location["size_bytes"]
                or f"{member.CRC:08x}" != location["crc32"]
            ):
                raise ValueError("Media archive member changed")
            with archive.open(member) as stream:
                yield stream
    else:
        with path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            if (
                stat.st_size != location["size_bytes"]
                or stat.st_mtime_ns != location["mtime_ns"]
            ):
                raise ValueError("Source file changed")
            yield stream
