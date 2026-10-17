"""Streaming reader for RetroArch's MessagePack-based RDB format."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
import struct

import msgpack


RDB_MAGIC = b"RARCHDB\0"
HEADER = struct.Struct("8sQ")


class RdbReader:
    """Read records without retaining an entire compiled database in memory."""

    def __init__(self, path: Path):
        self.path = path
        self.metadata_offset: int | None = None
        self.metadata: dict[str, object] = {}

    def records(self) -> Iterator[dict[str, object]]:
        self.metadata = {}
        with self.path.open("rb") as handle:
            header = handle.read(HEADER.size)
            if len(header) != HEADER.size:
                raise ValueError(f"RDB header is truncated: {self.path}")
            magic, self.metadata_offset = HEADER.unpack(header)
            if magic != RDB_MAGIC:
                raise ValueError(f"RDB magic is invalid: {self.path}")

            unpacker = msgpack.Unpacker(
                handle, raw=False, strict_map_key=False,
                unicode_errors="replace",
            )
            records_finished = False
            for value in unpacker:
                if value is None:
                    records_finished = True
                    continue
                if not isinstance(value, Mapping):
                    raise ValueError(
                        f"Unexpected RDB value {type(value).__name__}: {self.path}"
                    )
                document = {
                    self._key(key): item for key, item in value.items()
                }
                if records_finished or (
                    len(document) == 1 and "count" in document
                ):
                    self.metadata.update(document)
                else:
                    yield document

    @staticmethod
    def _key(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
