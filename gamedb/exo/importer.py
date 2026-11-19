"""Publish the inventoried source in one PostgreSQL transaction."""
from datetime import datetime, timezone
from itertools import islice
import json

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import JSONB

from . import schema


def write_rows(connection, table, snapshot_id, rows):
    columns = list(table.columns)
    driver = connection.connection.driver_connection
    with driver.cursor() as cursor:
        if hasattr(cursor, 'copy'):
            names = ', '.join(col.name for col in columns)
            json_indices = [i for i, col in enumerate(columns) if isinstance(col.type, JSONB)]
            with cursor.copy(f'COPY {table.fullname} ({names}) FROM STDIN') as stream:
                for row in rows:
                    values = [snapshot_id, *row]
                    for i in json_indices:
                        values[i] = json.dumps(values[i], ensure_ascii=False)
                    stream.write_row(values)
            return
    # Workstation deployments may use psycopg2.
    rows = iter(rows)
    while batch := list(islice(rows, 500)):
        connection.execute(insert(table), [
            dict(zip((c.name for c in columns), (snapshot_id, *row), strict=True))
            for row in batch
        ])


def publish(engine, root, inventory, progress=lambda msg: None):
    primary = {r.number for r in inventory.games.values()}
    counts = inventory.counts()
    with engine.begin() as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(721044285)'))
        connection.execute(text('CREATE SCHEMA IF NOT EXISTS staging'))
        schema.metadata.create_all(connection)
        existing = connection.execute(select(schema.snapshot.c.id).where(
            schema.snapshot.c.source_revision == inventory.revision
        )).scalar_one_or_none()
        if existing is not None:
            return {'snapshot_id': existing, 'already_imported': True, 'source_revision': inventory.revision, **counts}
        snapshot_id = connection.execute(insert(schema.snapshot).values(
            source_revision=inventory.revision, source_root=str(root), counts=counts,
            imported_at=datetime.now(timezone.utc),
        ).returning(schema.snapshot.c.id)).scalar_one()

        def save(table, rows):
            progress(f'Writing {table.fullname}')
            write_rows(connection, table, snapshot_id, rows)

        save(schema.document, ((path, *content) for path, content in inventory.documents.items()))
        save(schema.record, (
            (r.number, r.document, r.row, r.kind, r.platform, r.source_id, r.game_id,
             r.label, r.fields, r.number in primary) for r in inventory.records
        ))
        save(schema.asset, ((a.number, a.path, a.kind, a.category, a.region) for a in inventory.assets.values()))
        save(schema.location, (
            (loc.path, loc.member_no, asset, 'zip_member' if loc.member_no else
             ('url' if loc.size is None else 'file'), loc.member_name, loc.size, loc.crc32, loc.mtime_ns)
            for asset, loc in inventory.locations
        ))
        save(schema.image_evidence, inventory.image_evidence)
        save(schema.link, ((i, *link) for i, link in enumerate(sorted(inventory.links), 1)))
        save(schema.issue, ((i, *issue) for i, issue in enumerate(sorted(inventory.issues, key=repr), 1)))
    return {'snapshot_id': snapshot_id, 'already_imported': False, 'source_revision': inventory.revision, **counts}
