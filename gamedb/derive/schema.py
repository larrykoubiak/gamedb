"""Relational contract owned exclusively by the derivation package."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, MetaData, Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID


metadata = MetaData()

canonical_system = Table(
    "canonical_system", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("manufacturer_name", Text, nullable=False),
    Column("system_name", Text, nullable=False),
    UniqueConstraint("manufacturer_name", "system_name"),
    schema="ref",
)

system_mapping = Table(
    "system_mapping", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("romset", Text, nullable=False),
    Column("source_manufacturer", Text, nullable=False),
    Column("source_system", Text, nullable=False),
    Column("canonical_system_id", BigInteger, ForeignKey("ref.canonical_system.id"), nullable=False),
    Column("match_method", Text, nullable=False),
    Column("notes", Text),
    UniqueConstraint("romset", "source_manufacturer", "source_system"),
    schema="ref",
)

path_mapping = Table(
    "path_mapping", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("source_prefix", Text, nullable=False, unique=True),
    Column("target_prefix", Text, nullable=False),
    schema="ref",
)

tag_category = Table(
    "tag_category", metadata,
    Column("category", Text, primary_key=True),
    Column("description", Text, nullable=False),
    schema="ref",
)

software_correction = Table(
    "software_correction", metadata,
    Column("manufacturer_name", Text, primary_key=True),
    Column("system_name", Text, primary_key=True),
    Column("subject_content_signature", Text, primary_key=True),
    Column("action", Text, nullable=False),
    Column("target_content_signature", Text),
    Column("note", Text, nullable=False),
    CheckConstraint("subject_content_signature ~ '^[0-9a-f]{32}$'"),
    CheckConstraint("target_content_signature IS NULL OR target_content_signature ~ '^[0-9a-f]{32}$'"),
    CheckConstraint("action IN ('assign', 'separate')"),
    CheckConstraint("(action = 'assign' AND target_content_signature IS NOT NULL AND target_content_signature <> subject_content_signature) OR (action = 'separate' AND target_content_signature IS NULL)"),
    schema="ref",
)

dat_source = Table(
    "dat_source", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("dat_path", Text, nullable=False),
    Column("dat_name", Text, nullable=False),
    Column("romset", Text, nullable=False),
    Column("source_manufacturer", Text, nullable=False),
    Column("source_system", Text, nullable=False),
    Column("additional", JSONB, nullable=False),
    UniqueConstraint("dat_path", "dat_name"),
    schema="derived",
)

dat = Table(
    "dat", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("dat_source_id", BigInteger, ForeignKey("derived.dat_source.id"), nullable=False, unique=True),
    Column("dat_path", Text, nullable=False),
    Column("dat_name", Text, nullable=False),
    Column("romset", Text, nullable=False),
    Column("source_manufacturer", Text, nullable=False),
    Column("source_system", Text, nullable=False),
    Column("additional", JSONB, nullable=False),
    Column("system_mapping_id", BigInteger, ForeignKey("ref.system_mapping.id"), nullable=False),
    Column("canonical_system_id", BigInteger, ForeignKey("ref.canonical_system.id"), nullable=False),
    UniqueConstraint("dat_path", "dat_name"),
    schema="derived",
)

archive_name = Table(
    "archive_name", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("romset", Text, nullable=False),
    Column("archive_name", Text, nullable=False),
    Column("extension", Text, nullable=False),
    UniqueConstraint("romset", "archive_name"),
    schema="derived",
)

package = Table(
    "package", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("dat_id", BigInteger, ForeignKey("derived.dat.id"), nullable=False),
    Column("archive_name_id", BigInteger, ForeignKey("derived.archive_name.id"), nullable=False),
    Column("staged_file_count", BigInteger, nullable=False),
    Column("source_tree_path", Text, nullable=False),
    UniqueConstraint("dat_id", "archive_name_id"),
    CheckConstraint("staged_file_count > 0"),
    schema="derived",
)

package_path = Table(
    "package_path", metadata,
    Column("package_id", BigInteger, ForeignKey("derived.package.id", ondelete="CASCADE"), primary_key=True),
    Column("path_mapping_id", BigInteger, ForeignKey("ref.path_mapping.id")),
    Column("resolved_path", Text),
    schema="derived",
)

file = Table(
    "file", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("package_id", BigInteger, ForeignKey("derived.package.id", ondelete="CASCADE"), nullable=False),
    Column("source_run_id", UUID(as_uuid=True), nullable=False),
    Column("source_exported_at", DateTime(timezone=True), nullable=False),
    Column("source_full_path", Text),
    Column("member_path", Text, nullable=False),
    Column("file_name", Text),
    Column("size", BigInteger),
    Column("crc_hex", Text),
    Column("sha1_hex", Text),
    Column("md5_hex", Text),
    Column("alt_size", BigInteger),
    Column("alt_crc_hex", Text),
    Column("alt_sha1_hex", Text),
    Column("alt_md5_hex", Text),
    Column("sha1_verified", Boolean, nullable=False),
    Column("md5_verified", Boolean, nullable=False),
    Column("crc_verified", Boolean, nullable=False),
    Column("size_verified", Boolean, nullable=False),
    Column("deep_scanned", Boolean, nullable=False),
    Column("dat_status", Integer, nullable=False),
    Column("got_status", Integer, nullable=False),
    Column("rep_status", Integer, nullable=False),
    Column("source_game_id", Text),
    Column("source_game_description", Text),
    schema="derived",
)

translation_member_title = Table(
    "translation_member_title", metadata,
    Column("file_id", BigInteger, ForeignKey("derived.file.id", ondelete="CASCADE"), primary_key=True),
    Column("title_text", Text, nullable=False),
    Column("parse_status", Text, nullable=False),
    Column("parse_issues", JSONB, nullable=False),
    Column("parser_version", Text, nullable=False),
    CheckConstraint("btrim(title_text) <> ''"),
    schema="derived",
)

archive_parse = Table(
    "archive_parse", metadata,
    Column("archive_name_id", BigInteger, ForeignKey("derived.archive_name.id", ondelete="CASCADE"), primary_key=True),
    Column("parse_status", Text, nullable=False),
    Column("parse_issues", JSONB, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("classifier_version", Text, nullable=False),
    schema="derived",
)

record = Table(
    "record", metadata,
    Column("archive_name_id", BigInteger, primary_key=True),
    Column("record_index", Integer, primary_key=True),
    Column("title_text", Text, nullable=False),
    Column("source_start", Integer, nullable=False),
    Column("source_end", Integer, nullable=False),
    Column("parse_status", Text, nullable=False),
    Column("parse_issues", JSONB, nullable=False),
    Column("classification_issues", JSONB, nullable=False),
    Column("grouping_signature", Text, nullable=False),
    ForeignKeyConstraint(["archive_name_id"], ["derived.archive_name.id"], ondelete="CASCADE"),
    CheckConstraint("record_index > 0"),
    schema="derived",
)

tag = Table(
    "tag", metadata,
    Column("archive_name_id", BigInteger, primary_key=True),
    Column("record_index", Integer, primary_key=True),
    Column("tag_index", Integer, primary_key=True),
    Column("raw_value", Text, nullable=False),
    Column("delimiter", Text, nullable=False),
    Column("source_start", Integer, nullable=False),
    Column("source_end", Integer, nullable=False),
    ForeignKeyConstraint(
        ["archive_name_id", "record_index"],
        ["derived.record.archive_name_id", "derived.record.record_index"],
        ondelete="CASCADE",
    ),
    schema="derived",
)

tag_classification = Table(
    "tag_classification", metadata,
    Column("archive_name_id", BigInteger, primary_key=True),
    Column("record_index", Integer, primary_key=True),
    Column("tag_index", Integer, primary_key=True),
    Column("identifier", Text),
    Column("value", Text),
    Column("category", Text, ForeignKey("ref.tag_category.category"), nullable=False),
    Column("classification_status", Text, nullable=False),
    Column("rule", Text, nullable=False),
    Column("details", JSONB, nullable=False),
    ForeignKeyConstraint(
        ["archive_name_id", "record_index", "tag_index"],
        ["derived.tag.archive_name_id", "derived.tag.record_index", "derived.tag.tag_index"],
        ondelete="CASCADE",
    ),
    schema="derived",
)

assertion = Table(
    "assertion", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("archive_name_id", BigInteger, nullable=False),
    Column("record_index", Integer, nullable=False),
    Column("source_tag_index", Integer, nullable=False),
    Column("assertion_key", Text, nullable=False),
    Column("assertion_value", Text, nullable=False),
    ForeignKeyConstraint(
        ["archive_name_id", "record_index", "source_tag_index"],
        ["derived.tag.archive_name_id", "derived.tag.record_index", "derived.tag.tag_index"],
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "archive_name_id", "record_index", "source_tag_index",
        "assertion_key", "assertion_value",
    ),
    schema="derived",
)

media_part = Table(
    "media_part", metadata,
    Column("archive_name_id", BigInteger, primary_key=True),
    Column("record_index", Integer, primary_key=True),
    Column("source_tag_index", Integer, primary_key=True),
    Column("media_type", Text, nullable=False),
    Column("part", Text, nullable=False),
    Column("sequence", Integer),
    Column("total", Integer),
    Column("total_label", Text),
    Column("side", Text),
    Column("label", Text),
    Column("description", Text),
    ForeignKeyConstraint(
        ["archive_name_id", "record_index", "source_tag_index"],
        ["derived.tag.archive_name_id", "derived.tag.record_index", "derived.tag.tag_index"],
        ondelete="CASCADE",
    ),
    schema="derived",
)

source_release = Table(
    "source_release", metadata,
    Column("dat_id", BigInteger, ForeignKey("derived.dat.id"), primary_key=True),
    Column("group_ordinal", Integer, primary_key=True),
    Column("canonical_system_id", BigInteger, ForeignKey("ref.canonical_system.id"), nullable=False),
    Column("title_text", Text, nullable=False),
    Column("grouping_status", Text, nullable=False),
    Column("expected_media_parts", Integer),
    Column("available_media_parts", Integer),
    Column("needs_review", Boolean, nullable=False),
    schema="derived",
)

source_release_package = Table(
    "source_release_package", metadata,
    Column("source_dat_id", BigInteger, primary_key=True),
    Column("source_group_ordinal", Integer, primary_key=True),
    Column("package_id", BigInteger, ForeignKey("derived.package.id"), primary_key=True),
    Column("archive_name_id", BigInteger, nullable=False),
    Column("record_index", Integer, nullable=False),
    Column("media_type", Text),
    Column("media_part", Text),
    Column("media_sequence", Integer),
    Column("media_total", Integer),
    Column("media_total_label", Text),
    Column("media_side", Text),
    Column("media_label", Text),
    Column("media_description", Text),
    ForeignKeyConstraint(
        ["source_dat_id", "source_group_ordinal"],
        ["derived.source_release.dat_id", "derived.source_release.group_ordinal"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["archive_name_id", "record_index"],
        ["derived.record.archive_name_id", "derived.record.record_index"],
    ),
    UniqueConstraint("package_id", "archive_name_id", "record_index"),
    schema="derived",
)

Index("derived_dat_system_idx", dat.c.canonical_system_id)
Index("derived_package_dat_idx", package.c.dat_id)
Index("derived_file_package_idx", file.c.package_id)
Index("derived_file_sha1_idx", file.c.sha1_hex, postgresql_where=file.c.sha1_hex.is_not(None))
Index("derived_translation_member_title_idx", translation_member_title.c.title_text)
Index("derived_record_title_idx", record.c.title_text)
Index("derived_assertion_key_value_idx", assertion.c.assertion_key, assertion.c.assertion_value)

# Arcade interpretation is machine-scoped and independent of physical ZIP names.
arcade_release = Table(
    'arcade_release', metadata,
    Column('dat_id', BigInteger, primary_key=True),
    Column('group_ordinal', Integer, primary_key=True),
    Column('source_key', Text, nullable=False),
    Column('shortname', Text, nullable=False),
    Column('family', Text, nullable=False),
    Column('description', Text, nullable=False),
    Column('version', Text, nullable=False),
    Column('install_signature', Text, nullable=False, unique=True),
    Column('plan', JSONB, nullable=False),
    ForeignKeyConstraint(['dat_id', 'group_ordinal'],
                         ['derived.source_release.dat_id', 'derived.source_release.group_ordinal'], ondelete='CASCADE'),
    schema='derived',
)

Index("derived_release_package_record_idx", source_release_package.c.archive_name_id, source_release_package.c.record_index)
