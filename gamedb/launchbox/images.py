"""Import image references from a retained, already identified LaunchBox ZIP."""
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import insert, select, text

from . import schema
from .importer import records, sha256_file


def import_images(engine, path):
    path = Path(path)
    revision = sha256_file(path)
    with engine.begin() as c:
        c.execute(text('SELECT pg_advisory_xact_lock(721044281)'))
        schema.metadata.create_all(c)
        snapshot = c.execute(select(schema.snapshot).where(
            schema.snapshot.c.source_revision == revision
        )).mappings().one_or_none()
        if snapshot is None:
            raise ValueError('Import this ZIP with import-launchbox import first')
        import_id = snapshot['id']
        count = c.execute(select(schema.image_import.c.image_count).where(
            schema.image_import.c.import_id == import_id
        )).scalar_one_or_none()
        if count is not None:
            return dict(source_revision=revision, images=count, already_imported=True)
        count = 0
        batch = []
        with ZipFile(path) as archive, archive.open('Metadata.xml') as stream:
            for row, kind, fields, _ in records(stream):
                if kind != 'GameImage':
                    continue
                count += 1
                batch.append(dict(import_id=import_id, row_number=row,
                                  database_id=int(fields['DatabaseID']),
                                  file_name=fields['FileName'], image_type=fields['Type'],
                                  region=fields.get('Region', ''), raw_record=fields))
                if len(batch) >= 5000:
                    c.execute(insert(schema.image_record), batch)
                    batch.clear()
                    if count % 100000 == 0:
                        print(f'  LaunchBox: imported {count:,} image references', flush=True)
            if batch:
                c.execute(insert(schema.image_record), batch)
        if count != snapshot['record_counts'].get('GameImage', 0):
            raise ValueError('Image count differs from the game snapshot')
        if sha256_file(path) != revision:
            raise ValueError('Source ZIP changed during image import')
        c.execute(insert(schema.image_import).values(import_id=import_id, image_count=count))
        c.execute(text('''CREATE INDEX IF NOT EXISTS launchbox_image_game_idx
            ON staging.launchbox_image(import_id,database_id)'''))
    return dict(source_revision=revision, images=count, already_imported=False)
