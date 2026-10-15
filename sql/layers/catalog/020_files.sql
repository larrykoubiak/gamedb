-- Copy source file observations into their owning catalog packages and resolve
-- physical archive paths through maintained prefix mappings.
INSERT INTO catalog.file (
    package_id, source_run_id, source_exported_at, source_tree_path,
    source_full_path, member_path, file_name, size, crc_hex, sha1_hex, md5_hex,
    alt_size, alt_crc_hex, alt_sha1_hex, alt_md5_hex, sha1_verified,
    md5_verified, crc_verified, size_verified, deep_scanned, dat_status,
    got_status, rep_status, source_game_id, source_game_description
)
SELECT p.id, rf.run_id, rf.exported_at, rf.tree_full_name, rf.full_path,
    split_part(rf.tree_full_name, '/' || p.archive_name || '/', 2),
    rf.name, rf.size, rf.crc_hex, rf.sha1_hex, rf.md5_hex, rf.alt_size,
    rf.alt_crc_hex, rf.alt_sha1_hex, rf.alt_md5_hex, rf.sha1_verified,
    rf.md5_verified, rf.crc_verified, rf.size_verified, rf.deep_scanned,
    rf.dat_status, rf.got_status, rf.rep_status, rf.game_id,
    coalesce(rf.game_description, rf.game_description_ui)
FROM catalog.package p
JOIN derived.archive a ON a.id = p.source_archive_id
JOIN derived.dat d ON d.id = a.dat_id
JOIN derived.archive_name n ON n.id = a.archive_name_id
JOIN staging.rv_files rf
  ON rf.dat_root_full_name = d.dat_path
 AND rf.dat_name = d.dat_name
 AND rf.game_display_name = n.archive_name
ORDER BY p.id, rf.full_path, rf.name, rf.size, rf.sha1_hex;

-- RomVault paths identify both an archive and a member inside it. The package
-- owns the archive path; catalog.file.member_path owns the path within it.
UPDATE catalog.package p
SET source_tree_path = paths.source_tree_path
FROM (
    SELECT package_id,
        min(left(
            source_tree_path,
            length(source_tree_path) - length(member_path) - 1
        )) AS source_tree_path
    FROM catalog.file
    GROUP BY package_id
) paths
WHERE paths.package_id = p.id;

WITH selected_mapping AS (
    SELECT p.id AS package_id, mapping.id AS mapping_id,
        mapping.source_prefix, mapping.target_prefix
    FROM catalog.package p
    JOIN LATERAL (
        SELECT m.id, m.source_prefix, m.target_prefix
        FROM ref.path_mapping m
        WHERE p.source_tree_path = m.source_prefix
           OR p.source_tree_path LIKE m.source_prefix || '/%'
        ORDER BY length(m.source_prefix) DESC
        LIMIT 1
    ) mapping ON true
)
UPDATE catalog.package p
SET path_mapping_id = mapping.mapping_id,
    resolved_path = mapping.target_prefix
        || substr(p.source_tree_path, length(mapping.source_prefix) + 1)
FROM selected_mapping mapping
WHERE mapping.package_id = p.id;

ALTER TABLE catalog.package
    ALTER COLUMN source_tree_path SET NOT NULL;
