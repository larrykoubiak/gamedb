"""Stream the official Metadata.zip into an atomic, content-addressed snapshot."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from xml.etree.ElementTree import iterparse, tostring
from zipfile import ZipFile

from sqlalchemy import insert, select, text, update

from . import schema

SOURCE_URL = "https://gamesdb.launchbox-app.com/Metadata.zip"
RETAINED_TYPES = {"Game", "GameAlternateName", "Platform", "PlatformAlternateName"}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def records(stream):
    """Yield top-level records while releasing parsed XML, including image rows."""
    events = iterparse(stream, events=("start", "end"))
    _, root = next(events)
    if root.tag != "LaunchBox":
        raise ValueError(f"expected LaunchBox XML root, got {root.tag!r}")
    depth = 1
    row_number = 0
    for event, element in events:
        if event == "start":
            depth += 1
        else:
            if depth == 2:
                row_number += 1
                fields = {child.tag: child.text or "" for child in element}
                yield row_number, element.tag, fields, (
                    tostring(element, encoding="unicode")
                    if element.tag in RETAINED_TYPES else None
                )
                root.remove(element)
            depth -= 1


class LaunchBoxImporter:
    def __init__(self, engine, path, source_url=SOURCE_URL):
        self.engine = engine
        self.path = Path(path).resolve()
        self.source_url = source_url

    def execute(self):
        revision = sha256_file(self.path)
        with self.engine.begin() as connection:
            # Serialize same-source imports, including schema/existence checks.
            connection.execute(text("SELECT pg_advisory_xact_lock(721044281)"))
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
            schema.metadata.create_all(connection)
            existing = connection.execute(select(schema.snapshot).where(
                schema.snapshot.c.source_revision == revision
            )).mappings().one_or_none()
            if existing:
                return {"source_revision": revision, "record_counts": existing["record_counts"], "already_imported": True}
            import_id = connection.execute(insert(schema.snapshot).values(
                source_revision=revision, source_path=str(self.path),
                source_url=self.source_url, imported_at=datetime.now(timezone.utc),
                record_counts={},
            ).returning(schema.snapshot.c.id)).scalar_one()
            counts = Counter()
            game_ids = set()
            batch = []
            with ZipFile(self.path) as archive, archive.open("Metadata.xml") as stream:
                for row_number, kind, fields, raw_xml in records(stream):
                    counts[kind] += 1
                    if kind not in RETAINED_TYPES:
                        continue
                    database_id = None
                    if kind in {"Game", "GameAlternateName"}:
                        database_id = int(fields["DatabaseID"])
                        if database_id <= 0:
                            raise ValueError(f"invalid DatabaseID at row {row_number}")
                    if kind == "Game":
                        if not (fields.get("Name", "").strip() and fields.get("Platform", "").strip()):
                            raise ValueError(f"missing game name/platform at row {row_number}")
                        if database_id in game_ids:
                            raise ValueError(f"duplicate Game DatabaseID: {database_id}")
                        game_ids.add(database_id)
                    batch.append(dict(import_id=import_id, row_number=row_number,
                                      record_type=kind, database_id=database_id,
                                      raw_record=fields, raw_xml=raw_xml))
                    if len(batch) >= 2000:
                        connection.execute(insert(schema.record), batch)
                        batch.clear()
                if batch:
                    connection.execute(insert(schema.record), batch)
            if not counts["Game"]:
                raise ValueError("snapshot contains no Game records")
            if sha256_file(self.path) != revision:
                raise ValueError("source ZIP changed during import")
            connection.execute(update(schema.snapshot).where(
                schema.snapshot.c.id == import_id
            ).values(record_counts=dict(counts)))
        return {"source_revision": revision, "record_counts": dict(counts), "already_imported": False}
