"""Retained machine metadata; independent of disposable catalog rebuilds."""

from sqlalchemy import Boolean, Column, ForeignKey, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
source = Table(
    "arcade_source",
    metadata,
    Column("source_key", Text, primary_key=True),
    Column("version", Text, nullable=False),
    Column("xml_sha256", Text, nullable=False),
    Column("arcade_sha256", Text, nullable=False),
    Column("rom_dat_path", Text, nullable=False, unique=True),
    Column("chd_dat_path", Text, nullable=False, unique=True),
    Column("build", Text, nullable=False),
    schema="staging",
)
machine = Table(
    "arcade_machine",
    metadata,
    Column(
        "source_key",
        Text,
        ForeignKey("staging.arcade_source.source_key", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("name", Text, primary_key=True),
    Column("is_arcade", Boolean, nullable=False),
    Column("definition", JSONB, nullable=False),
    schema="staging",
)

samples = Table(
    "arcade_samples",
    metadata,
    Column(
        "source_key",
        Text,
        ForeignKey("staging.arcade_source.source_key", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("name", Text, primary_key=True),
    Column("dat_path", Text, nullable=False),
    Column("dat_sha256", Text, nullable=False),
    Column("definition", JSONB, nullable=False),
    schema="staging",
)
