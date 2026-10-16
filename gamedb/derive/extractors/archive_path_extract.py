"""Resolve stable package paths through maintained prefix mappings."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


class ArchivePathExtractor:
    version = "1"

    def execute(self, connection: Connection) -> None:
        connection.execute(text("TRUNCATE derived.package_path"))
        connection.execute(text("""
            INSERT INTO derived.package_path (
                package_id, path_mapping_id, resolved_path
            )
            SELECT p.id, mapping.id,
                mapping.target_prefix
                    || substr(p.source_tree_path, length(mapping.source_prefix) + 1)
            FROM derived.package p
            LEFT JOIN LATERAL (
                SELECT m.id, m.source_prefix, m.target_prefix
                FROM ref.path_mapping m
                WHERE p.source_tree_path = m.source_prefix
                   OR p.source_tree_path LIKE m.source_prefix || '/%'
                ORDER BY length(m.source_prefix) DESC
                LIMIT 1
            ) mapping ON true
            ORDER BY p.id
        """))
