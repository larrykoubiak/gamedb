"""Durable staging contract for maintained integrated packages."""

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, MetaData, Table,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID


metadata = MetaData()

integrated_package = Table(
    "integrated_package", metadata,
    Column("relative_path", Text, primary_key=True),
    Column("import_run_id", UUID(as_uuid=True), nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("source_manufacturer", Text, nullable=False),
    Column("source_system", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("region", Text, nullable=False),
    Column("modification", Text, nullable=False),
    Column("variant", Text),
    Column("catalog_archive_name", Text, nullable=False, unique=True),
    Column("media_type", Text),
    Column("media_part", Text),
    Column("media_sequence", Integer),
    Column("media_total", Integer),
    Column("archive_size", BigInteger, nullable=False),
    schema="staging",
)

integrated_file = Table(
    "integrated_file", metadata,
    Column(
        "package_relative_path", Text,
        ForeignKey(
            "staging.integrated_package.relative_path", ondelete="CASCADE"
        ),
        primary_key=True,
    ),
    Column("member_index", Integer, primary_key=True),
    Column("member_path", Text, nullable=False),
    Column("file_name", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("crc_hex", Text, nullable=False),
    Column("sha1_hex", Text, nullable=False),
    Column("crc_verified", Boolean, nullable=False),
    schema="staging",
)
