"""Project stable packages and files from staging without parsing their names."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


class InventoryExtractor:
    """Build source inventory independently from archive-name interpretation."""

    version = "1"

    def execute(self, connection: Connection) -> None:
        connection.execute(text("DROP SCHEMA IF EXISTS catalog CASCADE"))
        connection.execute(text("""
            TRUNCATE derived.archive_name RESTART IDENTITY CASCADE
        """))
        connection.execute(text("""
            INSERT INTO derived.archive_name (romset, archive_name, extension)
            SELECT DISTINCT d.romset, rf.game_display_name,
                CASE WHEN lower(rf.game_display_name) LIKE '%.zip'
                    THEN right(rf.game_display_name, 4) ELSE '' END
            FROM staging.rv_files rf
            JOIN derived.dat d
              ON d.dat_path = rf.dat_root_full_name
             AND d.dat_name = rf.dat_name
            WHERE nullif(btrim(rf.game_display_name), '') IS NOT NULL
            ORDER BY d.romset, rf.game_display_name
        """))
        connection.execute(text("""
            INSERT INTO derived.archive_name (romset, archive_name, extension)
            SELECT DISTINCT 'Integrated', source.catalog_archive_name, '.zip'
            FROM staging.integrated_package source
            ORDER BY source.catalog_archive_name
        """))
        connection.execute(text("""
            INSERT INTO derived.package (
                dat_id, archive_name_id, staged_file_count, source_tree_path
            )
            SELECT d.id, n.id, count(*),
                min(left(
                    rf.tree_full_name,
                    length(rf.tree_full_name)
                        - length(split_part(
                            rf.tree_full_name,
                            '/' || rf.game_display_name || '/', 2
                        )) - 1
                ))
            FROM staging.rv_files rf
            JOIN derived.dat d
              ON d.dat_path = rf.dat_root_full_name
             AND d.dat_name = rf.dat_name
            JOIN derived.archive_name n
              ON n.romset = d.romset
             AND n.archive_name = rf.game_display_name
            GROUP BY d.id, n.id
            ORDER BY d.id, n.id
        """))
        connection.execute(text("""
            INSERT INTO derived.package (
                dat_id, archive_name_id, staged_file_count, source_tree_path
            )
            SELECT dat.id, archive.id, count(file.member_index),
                'Integrated/Undub/' || source.relative_path
            FROM staging.integrated_package source
            JOIN staging.integrated_file file
              ON file.package_relative_path = source.relative_path
            JOIN derived.dat dat
              ON dat.romset = 'Integrated'
             AND dat.source_manufacturer = source.source_manufacturer
             AND dat.source_system = source.source_system
            JOIN derived.archive_name archive
              ON archive.romset = 'Integrated'
             AND archive.archive_name = source.catalog_archive_name
            GROUP BY dat.id, archive.id, source.relative_path
            ORDER BY dat.id, archive.id
        """))
        connection.execute(text("""
            INSERT INTO derived.file (
                package_id, source_run_id, source_exported_at, source_full_path,
                member_path, file_name, size, crc_hex, sha1_hex, md5_hex,
                alt_size, alt_crc_hex, alt_sha1_hex, alt_md5_hex,
                sha1_verified, md5_verified, crc_verified, size_verified,
                deep_scanned, dat_status, got_status, rep_status,
                source_game_id, source_game_description
            )
            SELECT p.id, rf.run_id, rf.exported_at, rf.full_path,
                split_part(rf.tree_full_name, '/' || n.archive_name || '/', 2),
                rf.name, rf.size, rf.crc_hex, rf.sha1_hex, rf.md5_hex,
                rf.alt_size, rf.alt_crc_hex, rf.alt_sha1_hex, rf.alt_md5_hex,
                rf.sha1_verified, rf.md5_verified, rf.crc_verified,
                rf.size_verified, rf.deep_scanned, rf.dat_status,
                rf.got_status, rf.rep_status, rf.game_id,
                coalesce(rf.game_description, rf.game_description_ui)
            FROM derived.package p
            JOIN derived.dat d ON d.id = p.dat_id
            JOIN derived.archive_name n ON n.id = p.archive_name_id
            JOIN staging.rv_files rf
              ON rf.dat_root_full_name = d.dat_path
             AND rf.dat_name = d.dat_name
             AND rf.game_display_name = n.archive_name
            ORDER BY p.id, rf.full_path, rf.name, rf.size, rf.sha1_hex
        """))
        connection.execute(text("""
            INSERT INTO derived.file (
                package_id, source_run_id, source_exported_at,
                source_full_path, member_path, file_name, size, crc_hex,
                sha1_hex, md5_hex, alt_size, alt_crc_hex, alt_sha1_hex,
                alt_md5_hex, sha1_verified, md5_verified, crc_verified,
                size_verified, deep_scanned, dat_status, got_status,
                rep_status, source_game_id, source_game_description
            )
            SELECT package.id, source.import_run_id, source.imported_at,
                'Integrated/Undub/' || source.relative_path,
                file.member_path, file.file_name, file.size, file.crc_hex,
                file.sha1_hex, NULL, NULL, NULL, NULL, NULL,
                false, false, file.crc_verified, true, true,
                0, 0, 0, source.relative_path, source.title
            FROM staging.integrated_package source
            JOIN staging.integrated_file file
              ON file.package_relative_path = source.relative_path
            JOIN derived.dat dat
              ON dat.romset = 'Integrated'
             AND dat.source_manufacturer = source.source_manufacturer
             AND dat.source_system = source.source_system
            JOIN derived.archive_name archive
              ON archive.romset = 'Integrated'
             AND archive.archive_name = source.catalog_archive_name
            JOIN derived.package package
              ON package.dat_id = dat.id
             AND package.archive_name_id = archive.id
            ORDER BY package.id, file.member_index
        """))
