"""LaunchBox-owned staging tables; catalog identities are never written here."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(schema="staging")
snapshot = Table(
    "launchbox_import", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("source_revision", Text, nullable=False, unique=True),
    Column("source_path", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("record_counts", JSONB, nullable=False),
)
record = Table(
    "launchbox_record", metadata,
    Column("import_id", BigInteger, ForeignKey("staging.launchbox_import.id", ondelete="CASCADE"), primary_key=True),
    Column("row_number", BigInteger, primary_key=True),
    Column("record_type", Text, nullable=False),
    Column("database_id", BigInteger),
    Column("raw_record", JSONB, nullable=False),
    Column("raw_xml", Text, nullable=False),
)

image_import = Table(
    "launchbox_image_import", metadata,
    Column("import_id", BigInteger, ForeignKey("staging.launchbox_import.id", ondelete="CASCADE"), primary_key=True),
    Column("image_count", BigInteger, nullable=False),
)
image_record = Table(
    "launchbox_image", metadata,
    Column("import_id", BigInteger, ForeignKey("staging.launchbox_import.id", ondelete="CASCADE"), primary_key=True),
    Column("row_number", BigInteger, primary_key=True),
    Column("database_id", BigInteger, nullable=False),
    Column("file_name", Text, nullable=False),
    Column("image_type", Text, nullable=False),
    Column("region", Text, nullable=False),
    Column("raw_record", JSONB, nullable=False),
)
