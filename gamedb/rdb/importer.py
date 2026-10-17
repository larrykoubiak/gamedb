"""Import a pinned libretro-database checkout into revisioned staging rows."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import subprocess
from typing import Mapping

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.engine import Connection, Engine

from .reader import RdbReader
from . import schema


BATCH_SIZE = 5_000
DEFAULT_SOURCE_URL = "https://github.com/libretro/libretro-database.git"
GIT_REVISION = re.compile(r"[0-9a-f]{40}")


def _git(checkout: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


def resolve_rdb_directory(checkout: Path) -> tuple[Path, Path]:
    """Return checkout root and its compiled RDB directory."""
    checkout = checkout.resolve()
    nested = checkout / "rdb"
    if nested.is_dir():
        return checkout, nested
    if checkout.is_dir() and any(checkout.glob("*.rdb")):
        return checkout, checkout
    raise FileNotFoundError(f"no compiled RDB directory found below {checkout}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def json_value(value: object) -> object:
    """Retain binary values and nested types in JSON without ambiguity."""
    if isinstance(value, bytes):
        return {"$binary_hex": value.hex()}
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"$python_type": type(value).__name__, "$text": str(value)}


def normalized_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip() or None
    return str(value).strip() or None


def normalized_hash(value: object, expected_length: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        result = value.hex()
    else:
        result = str(value).strip().lower()
        if result.startswith("0x"):
            result = result[2:]
    result = "".join(character for character in result if character in "0123456789abcdef")
    return result if len(result) == expected_length else None


def normalized_integer(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def field_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bytes):
        return "binary"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "text"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return type(value).__name__


class LibretroRdbImporter:
    """Write one complete Git revision without touching other staging owners."""

    def __init__(
        self, engine: Engine, checkout: Path, revision: str | None = None,
        source_url: str | None = None, replace: bool = False,
    ):
        self.engine = engine
        self.checkout, self.rdb_directory = resolve_rdb_directory(checkout)
        has_git_metadata = (self.checkout / ".git").exists()
        if revision is None and not has_git_metadata:
            raise ValueError(
                "--revision is required when the RDB directory is not a Git checkout"
            )
        self.revision = (revision or _git(
            self.checkout, "rev-parse", "HEAD"
        )).lower()
        if not GIT_REVISION.fullmatch(self.revision):
            raise ValueError("source revision must be a full 40-character Git hash")
        if has_git_metadata and _git(
            self.checkout, "status", "--porcelain", "--", "rdb"
        ):
            raise ValueError("the checkout has uncommitted changes below rdb/")
        self.source_url = source_url or self._source_url()
        self.replace = replace

    def _source_url(self) -> str:
        if not (self.checkout / ".git").exists():
            return DEFAULT_SOURCE_URL
        try:
            return _git(self.checkout, "remote", "get-url", "origin")
        except subprocess.CalledProcessError:
            return DEFAULT_SOURCE_URL

    def execute(self) -> dict[str, object]:
        paths = sorted(self.rdb_directory.glob("*.rdb"))
        if not paths:
            raise FileNotFoundError(f"no .rdb files found in {self.rdb_directory}")

        with self.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
            schema.metadata.create_all(connection)
            existing = connection.execute(
                select(schema.rdb_import).where(
                    schema.rdb_import.c.source_revision == self.revision
                )
            ).mappings().one_or_none()
            if existing is not None and not self.replace:
                return {
                    "source_revision": self.revision,
                    "rdb_files": existing["rdb_file_count"],
                    "entries": existing["entry_count"],
                    "already_imported": True,
                }
            if existing is not None:
                connection.execute(
                    delete(schema.rdb_import).where(
                        schema.rdb_import.c.id == existing["id"]
                    )
                )
            import_id = connection.execute(
                insert(schema.rdb_import).values(
                    source_revision=self.revision,
                    source_url=self.source_url,
                    source_path=str(self.checkout),
                    imported_at=datetime.now(timezone.utc),
                    rdb_file_count=0,
                    entry_count=0,
                    details={"format": "RetroArch RDB", "reader": "msgpack-stream-v1"},
                ).returning(schema.rdb_import.c.id)
            ).scalar_one()

            total_entries = 0
            all_fields: set[str] = set()
            for index, path in enumerate(paths, 1):
                count, fields = self._import_file(connection, import_id, path)
                total_entries += count
                all_fields.update(fields)
                print(
                    f"[{index}/{len(paths)}] {path.name}: {count:,} entries",
                    flush=True,
                )
            connection.execute(
                update(schema.rdb_import).where(
                    schema.rdb_import.c.id == import_id
                ).values(
                    rdb_file_count=len(paths),
                    entry_count=total_entries,
                    details={
                        "format": "RetroArch RDB",
                        "reader": "msgpack-stream-v1",
                        "field_names": sorted(all_fields),
                    },
                )
            )
        return {
            "source_revision": self.revision,
            "rdb_files": len(paths),
            "entries": total_entries,
            "already_imported": False,
        }

    def _import_file(
        self, connection: Connection, import_id: int, path: Path,
    ) -> tuple[int, set[str]]:
        relative_path = path.relative_to(self.checkout).as_posix()
        file_id = connection.execute(
            insert(schema.rdb_file).values(
                import_id=import_id,
                relative_path=relative_path,
                database_name=path.stem,
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
                declared_entry_count=None,
                entry_count=0,
                field_types={},
                metadata={},
            ).returning(schema.rdb_file.c.id)
        ).scalar_one()

        reader = RdbReader(path)
        types: dict[str, set[str]] = defaultdict(set)
        batch: list[dict[str, object]] = []
        count = 0
        for count, record in enumerate(reader.records(), 1):
            for key, value in record.items():
                types[key].add(field_type(value))
            batch.append(self._entry_row(file_id, count, record))
            if len(batch) >= BATCH_SIZE:
                connection.execute(insert(schema.rdb_entry), batch)
                batch.clear()
        if batch:
            connection.execute(insert(schema.rdb_entry), batch)

        metadata = json_value(reader.metadata)
        declared = normalized_integer(reader.metadata.get("count"))
        if declared is not None and declared != count:
            raise ValueError(
                f"{path} declares {declared:,} entries but contains {count:,}"
            )
        connection.execute(
            update(schema.rdb_file).where(schema.rdb_file.c.id == file_id).values(
                declared_entry_count=declared,
                entry_count=count,
                field_types={key: sorted(values) for key, values in types.items()},
                metadata=metadata,
            )
        )
        return count, set(types)

    @staticmethod
    def _entry_row(
        file_id: int, row_number: int, record: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "file_id": file_id,
            "row_number": row_number,
            "name": normalized_text(record.get("name")),
            "description": normalized_text(record.get("description")),
            "rom_name": normalized_text(record.get("rom_name")),
            "size": normalized_integer(record.get("size")),
            "crc_hex": normalized_hash(record.get("crc"), 8),
            "md5_hex": normalized_hash(record.get("md5"), 32),
            "sha1_hex": normalized_hash(record.get("sha1"), 40),
            "serial": normalized_text(record.get("serial")),
            "raw_record": json_value(record),
        }
