"""Durable, revisioned Libretro RDB source snapshots in staging."""

from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer, MetaData, Table,
    Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


metadata = MetaData()


rdb_import = Table(
    "libretro_rdb_import", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("source_revision", Text, nullable=False, unique=True),
    Column("source_url", Text, nullable=False),
    Column("source_path", Text, nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("rdb_file_count", Integer, nullable=False),
    Column("entry_count", BigInteger, nullable=False),
    Column("details", JSONB, nullable=False),
    schema="staging",
)

rdb_file = Table(
    "libretro_rdb_file", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "import_id", BigInteger,
        ForeignKey("staging.libretro_rdb_import.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("relative_path", Text, nullable=False),
    Column("database_name", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("declared_entry_count", BigInteger),
    Column("entry_count", BigInteger, nullable=False),
    Column("field_types", JSONB, nullable=False),
    Column("metadata", JSONB, nullable=False),
    UniqueConstraint("import_id", "relative_path"),
    schema="staging",
)

rdb_entry = Table(
    "libretro_rdb_entry", metadata,
    Column(
        "file_id", BigInteger,
        ForeignKey("staging.libretro_rdb_file.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("row_number", BigInteger, primary_key=True),
    Column("name", Text),
    Column("description", Text),
    Column("rom_name", Text),
    Column("size", BigInteger),
    Column("crc_hex", Text),
    Column("md5_hex", Text),
    Column("sha1_hex", Text),
    Column("serial", Text),
    Column("raw_record", JSONB, nullable=False),
    schema="staging",
)

Index(
    "libretro_rdb_entry_sha1_idx", rdb_entry.c.sha1_hex,
    postgresql_where=rdb_entry.c.sha1_hex.is_not(None),
)
Index(
    "libretro_rdb_entry_md5_idx", rdb_entry.c.md5_hex,
    postgresql_where=rdb_entry.c.md5_hex.is_not(None),
)
Index(
    "libretro_rdb_entry_crc_size_idx", rdb_entry.c.crc_hex, rdb_entry.c.size,
    postgresql_where=rdb_entry.c.crc_hex.is_not(None),
)
Index(
    "libretro_rdb_entry_serial_idx", rdb_entry.c.serial,
    postgresql_where=rdb_entry.c.serial.is_not(None),
)
