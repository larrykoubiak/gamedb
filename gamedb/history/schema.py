"""Tables for immutable historical-source snapshots in staging."""

from sqlalchemy import (
    BigInteger, Column, DateTime, Integer, MetaData, Table, Text,
)
from sqlalchemy.dialects.postgresql import JSONB


metadata = MetaData()


def history_table(name: str, *columns: Column) -> Table:
    return Table(name, metadata, *columns, schema="staging")


snapshot = history_table(
    "history_snapshot",
    Column("snapshot_key", Text, primary_key=True),
    Column("source_kind", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("source_locator", Text, nullable=False),
    Column("source_sha256", Text),
    Column("details", JSONB, nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
)

artifact = history_table(
    "history_artifact",
    Column("snapshot_key", Text, primary_key=True),
    Column("artifact_key", Text, primary_key=True),
    Column("role", Text, nullable=False),
    Column("source_path", Text, nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("modified_at", DateTime(timezone=True), nullable=False),
    Column("sha256", Text, nullable=False),
)

legacy_source = history_table(
    "history_legacy_source",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_source_id", BigInteger, primary_key=True),
    Column("source_name", Text),
    Column("source_url", Text),
    Column("source_order", Integer),
    Column("has_software_data", Integer),
    Column("has_dat_info", Integer),
    Column("has_release_data", Integer),
    Column("has_images", Integer),
)

legacy_source_rating = history_table(
    "history_legacy_source_rating",
    Column("snapshot_key", Text, primary_key=True),
    Column("subject_type", Text, primary_key=True),
    Column("legacy_rating_id", BigInteger, primary_key=True),
    Column("legacy_source_id", BigInteger),
    Column("legacy_flag_id", BigInteger),
    Column("flag_name", Text),
    Column("rating", Integer),
)

legacy_system = history_table(
    "history_legacy_system",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_system_id", BigInteger, primary_key=True),
    Column("system_name", Text),
    Column("manufacturer_name", Text),
    Column("system_format", Text),
    Column("system_acronym", Text),
)

legacy_software = history_table(
    "history_legacy_software",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_software_id", BigInteger, primary_key=True),
    Column("software_name", Text),
    Column("software_type", Text),
    Column("software_type_id", BigInteger),
    Column("legacy_system_id", BigInteger, nullable=False),
    Column("status_name", Text),
)

legacy_release = history_table(
    "history_legacy_release",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_release_id", BigInteger, primary_key=True),
    Column("release_name", Text),
    Column("region", Text),
    Column("release_type", Text),
    Column("legacy_software_id", BigInteger, nullable=False),
    Column("status_name", Text),
    Column("release_folder", Text),
)

legacy_file = history_table(
    "history_legacy_file",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_file_id", BigInteger, primary_key=True),
    Column("legacy_release_id", BigInteger, nullable=False),
    Column("file_name", Text),
    Column("size", BigInteger),
    Column("crc_hex", Text),
    Column("md5_hex", Text),
    Column("sha1_hex", Text),
    Column("file_status", Text),
)

legacy_claim = history_table(
    "history_legacy_claim",
    Column("snapshot_key", Text, primary_key=True),
    Column("subject_type", Text, primary_key=True),
    Column("legacy_claim_id", BigInteger, primary_key=True),
    Column("subject_id", BigInteger, nullable=False),
    Column("flag_name", Text, nullable=False),
    Column("flag_value", Text),
    Column("source_name", Text),
    Column("source_record_id", BigInteger),
)

python_dat_file = history_table(
    "history_python_dat_file",
    Column("snapshot_key", Text, primary_key=True),
    Column("dat_file_id", BigInteger, primary_key=True),
    Column("legacy_system_id", BigInteger),
    Column("file_name", Text),
    Column("dat_type", Text),
    Column("release_group", Text),
    Column("dat_date", Text),
)

python_dat_game = history_table(
    "history_python_dat_game",
    Column("snapshot_key", Text, primary_key=True),
    Column("dat_game_id", BigInteger, primary_key=True),
    Column("dat_file_id", BigInteger, nullable=False),
    Column("game_name", Text),
    Column("clone_of", Text),
    Column("rom_of", Text),
)

python_dat_rom = history_table(
    "history_python_dat_rom",
    Column("snapshot_key", Text, primary_key=True),
    Column("dat_rom_id", BigInteger, primary_key=True),
    Column("dat_file_id", BigInteger, nullable=False),
    Column("dat_game_id", BigInteger, nullable=False),
    Column("rom_name", Text),
    Column("merge_name", Text),
    Column("size", BigInteger),
    Column("crc_hex", Text),
    Column("md5_hex", Text),
    Column("sha1_hex", Text),
)

python_system = history_table(
    "history_python_system",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_system_id", BigInteger, primary_key=True),
    Column("system_name", Text),
    Column("manufacturer_name", Text),
)

python_software = history_table(
    "history_python_software",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_software_id", BigInteger, primary_key=True),
    Column("software_name", Text),
    Column("software_type", Text),
    Column("legacy_system_id", BigInteger, nullable=False),
)

python_release = history_table(
    "history_python_release",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_release_id", BigInteger, primary_key=True),
    Column("release_name", Text),
    Column("release_type", Text),
    Column("legacy_software_id", BigInteger, nullable=False),
)

python_rom = history_table(
    "history_python_rom",
    Column("snapshot_key", Text, primary_key=True),
    Column("legacy_rom_id", BigInteger, primary_key=True),
    Column("legacy_release_id", BigInteger, nullable=False),
    Column("size", BigInteger),
    Column("crc_hex", Text),
    Column("md5_hex", Text),
    Column("sha1_hex", Text),
)

python_external_game = history_table(
    "history_python_external_game",
    Column("snapshot_key", Text, primary_key=True),
    Column("external_game_id", BigInteger, primary_key=True),
    Column("source_name", Text),
    Column("external_system_id", BigInteger),
    Column("external_system_name", Text),
    Column("external_system_url", Text),
    Column("game_name", Text),
    Column("game_url", Text),
)

python_external_release = history_table(
    "history_python_external_release",
    Column("snapshot_key", Text, primary_key=True),
    Column("external_release_id", BigInteger, primary_key=True),
    Column("external_game_id", BigInteger, nullable=False),
    Column("release_name", Text),
    Column("region", Text),
    Column("release_type", Text),
)

python_map = history_table(
    "history_python_map",
    Column("snapshot_key", Text, primary_key=True),
    Column("row_number", BigInteger, primary_key=True),
    Column("map_type", Text, nullable=False),
    Column("left_id", BigInteger),
    Column("right_id", BigInteger),
)

python_synonym = history_table(
    "history_python_synonym",
    Column("snapshot_key", Text, primary_key=True),
    Column("synonym_type", Text, primary_key=True),
    Column("source_value", Text, primary_key=True),
    Column("normalized_value", Text, primary_key=True),
)

match_review = history_table(
    "history_match_review",
    Column("snapshot_key", Text, primary_key=True),
    Column("row_number", Integer, primary_key=True),
    Column("system_name", Text, nullable=False),
    Column("software_name", Text, nullable=False),
    Column("normalized_software_name", Text),
    Column("matched_external_name", Text),
    Column("match_method", Text),
    Column("original_score", Integer),
    Column("external_url", Text),
    Column("reviewed_score", Integer),
    Column("review_decision", Text, nullable=False),
)

workbook_row = history_table(
    "history_workbook_row",
    Column("snapshot_key", Text, primary_key=True),
    Column("artifact_key", Text, primary_key=True),
    Column("sheet_name", Text, primary_key=True),
    Column("row_number", Integer, primary_key=True),
    Column("values", JSONB, nullable=False),
)
