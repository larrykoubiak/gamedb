"""Immutable eXo source snapshots. All local identifiers are snapshot-scoped."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    Identity, Index, Integer, LargeBinary, MetaData, Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


metadata = MetaData(schema='staging')
snapshot = Table(
    'exo_snapshot', metadata,
    Column('id', BigInteger, Identity(), primary_key=True),
    Column('source_revision', Text, unique=True, nullable=False),
    Column('source_root', Text, nullable=False),
    Column('imported_at', DateTime(timezone=True), nullable=False),
    Column('counts', JSONB, nullable=False),
)


def child(name, *columns):
    return Table('exo_' + name, metadata,
                 Column('snapshot_id', BigInteger, ForeignKey('staging.exo_snapshot.id'),
                        primary_key=True), *columns)


def scoped_fk(column, target):
    return ForeignKeyConstraint(['snapshot_id', column],
                                ['staging.exo_' + target + '.snapshot_id',
                                 'staging.exo_' + target + '.' + column])


document = child('document',
    Column('document_path', Text, primary_key=True),
    Column('source_view', Text, nullable=False),
    Column('sha256', Text, nullable=False),
    Column('content', LargeBinary, nullable=False),
)
record = child('record',
    Column('record_no', Integer, primary_key=True, autoincrement=False),
    Column('document_path', Text, nullable=False), scoped_fk('document_path', 'document'),
    Column('row_number', Integer, nullable=False),
    Column('record_type', Text, nullable=False),
    Column('platform', Text), Column('source_id', Text), Column('game_id', Text),
    Column('label', Text), Column('fields', JSONB, nullable=False),
    Column('primary_game', Boolean, nullable=False),
    UniqueConstraint('snapshot_id', 'document_path', 'row_number'),
)
Index('exo_record_game_idx', record.c.snapshot_id, record.c.platform, record.c.game_id)
Index('exo_primary_game_idx', record.c.snapshot_id, record.c.platform, record.c.game_id,
      unique=True, postgresql_where=record.c.primary_game)
asset = child('asset',
    Column('asset_no', Integer, primary_key=True, autoincrement=False),
    Column('logical_path', Text, nullable=False),
    Column('kind', Text, nullable=False),
    Column('media_category', Text), Column('region', Text),
    UniqueConstraint('snapshot_id', 'logical_path'),
)
location = child('location',
    Column('source_path', Text, primary_key=True),
    Column('member_no', Integer, primary_key=True, autoincrement=False),
    Column('asset_no', Integer, nullable=False), scoped_fk('asset_no', 'asset'),
    Column('location_type', Text, nullable=False), Column('member_name', Text),
    Column('size_bytes', BigInteger), Column('crc32', Text), Column('mtime_ns', BigInteger),
    CheckConstraint("""(location_type='zip_member' AND member_no>0 AND member_name IS NOT NULL)
                    OR (location_type IN ('file','url') AND member_no=0 AND member_name IS NULL)"""),
)
Index('exo_location_asset_idx', location.c.snapshot_id, location.c.asset_no)
link = child('asset_link',
    Column('link_no', Integer, primary_key=True, autoincrement=False),
    Column('record_no', Integer, nullable=False), scoped_fk('record_no', 'record'),
    Column('asset_no', Integer, nullable=False), scoped_fk('asset_no', 'asset'),
    Column('role', Text, nullable=False), Column('basis', Text, nullable=False),
    Column('label', Text, nullable=False),
)
Index('exo_link_owner_idx', link.c.snapshot_id, link.c.record_no, link.c.role)
Index('exo_link_asset_idx', link.c.snapshot_id, link.c.asset_no)
issue = child('issue',
    Column('issue_no', Integer, primary_key=True, autoincrement=False),
    Column('kind', Text, nullable=False), Column('reference', Text, nullable=False),
    Column('record_no', Integer), scoped_fk('record_no', 'record'),
    Column('asset_no', Integer), scoped_fk('asset_no', 'asset'),
    Column('candidate_ids', JSONB, nullable=False),
)

image_evidence = child('image_evidence',
    Column('asset_no', Integer, primary_key=True, autoincrement=False), scoped_fk('asset_no', 'asset'),
    Column('source_path', Text, primary_key=True), Column('image_filename', Text, primary_key=True),
    Column('database_id', BigInteger, nullable=False), Column('media_category', Text, nullable=False),
    Column('region', Text), Column('crc32', Text, nullable=False),
)
