-- Build the consumer catalog from complete, typed derived source releases.
-- No source-name parsing, file loading, path resolution, or media inference
-- belongs in this layer.
\set ON_ERROR_STOP on
BEGIN;

DROP SCHEMA IF EXISTS catalog CASCADE;
CREATE SCHEMA catalog;

CREATE TABLE catalog.system (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_canonical_system_id bigint NOT NULL UNIQUE
        REFERENCES ref.canonical_system(id) ON DELETE RESTRICT,
    manufacturer_name text NOT NULL,
    system_name text NOT NULL,
    UNIQUE (manufacturer_name, system_name)
);

CREATE TABLE catalog.title (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id bigint NOT NULL REFERENCES catalog.system(id) ON DELETE RESTRICT,
    cluster_key text NOT NULL CHECK (btrim(cluster_key) <> ''),
    display_title text NOT NULL CHECK (btrim(display_title) <> ''),
    grouping_basis text NOT NULL CHECK (grouping_basis IN (
        'exact_title', 'reviewed_override'
    )),
    UNIQUE (system_id, cluster_key)
);

CREATE TABLE catalog.release (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title_id bigint NOT NULL REFERENCES catalog.title(id) ON DELETE RESTRICT,
    source_dat_id bigint NOT NULL REFERENCES derived.dat(id) ON DELETE RESTRICT,
    source_group_ordinal integer NOT NULL CHECK (source_group_ordinal > 0),
    display_title text NOT NULL CHECK (btrim(display_title) <> ''),
    grouping_status text NOT NULL CHECK (grouping_status IN (
        'standalone', 'media_singleton', 'media_grouped', 'media_complete',
        'media_ambiguous'
    )),
    expected_media_parts integer CHECK (expected_media_parts > 0),
    available_media_parts integer CHECK (available_media_parts > 0),
    UNIQUE (source_dat_id, source_group_ordinal)
);

CREATE TABLE catalog.package (
    id bigint PRIMARY KEY,
    source_dat_id bigint NOT NULL,
    source_archive_name_id bigint NOT NULL,
    source_collection text NOT NULL,
    dat_path text NOT NULL,
    archive_name text NOT NULL,
    source_tree_path text NOT NULL,
    resolved_path text,
    staged_file_count bigint NOT NULL CHECK (staged_file_count > 0)
);

CREATE TABLE catalog.package_file (
    id bigint PRIMARY KEY,
    package_id bigint NOT NULL REFERENCES catalog.package(id) ON DELETE CASCADE,
    source_full_path text,
    member_path text NOT NULL,
    file_name text,
    size bigint,
    crc_hex text,
    sha1_hex text,
    md5_hex text,
    sha1_verified boolean NOT NULL,
    md5_verified boolean NOT NULL,
    crc_verified boolean NOT NULL,
    size_verified boolean NOT NULL,
    deep_scanned boolean NOT NULL
);

CREATE TABLE catalog.release_package (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id bigint NOT NULL REFERENCES catalog.release(id) ON DELETE CASCADE,
    package_id bigint NOT NULL REFERENCES catalog.package(id) ON DELETE RESTRICT,
    source_archive_name_id bigint NOT NULL,
    source_record_index integer NOT NULL,
    media_type text,
    media_part text,
    media_sequence integer CHECK (media_sequence > 0),
    media_total integer CHECK (media_total > 0),
    media_total_label text,
    media_side text,
    media_label text,
    media_description text,
    FOREIGN KEY (source_archive_name_id, source_record_index)
        REFERENCES derived.record(archive_name_id, record_index)
        ON DELETE RESTRICT,
    UNIQUE (package_id, source_archive_name_id, source_record_index)
);

INSERT INTO catalog.system (
    source_canonical_system_id, manufacturer_name, system_name
)
SELECT id, manufacturer_name, system_name
FROM ref.canonical_system
ORDER BY manufacturer_name, system_name;

INSERT INTO catalog.title (
    system_id, cluster_key, display_title, grouping_basis
)
SELECT DISTINCT
    system.id,
    source.title_text,
    source.title_text,
    'exact_title'
FROM derived.source_release source
JOIN catalog.system system
  ON system.source_canonical_system_id = source.canonical_system_id
ORDER BY system.id, source.title_text;

INSERT INTO catalog.release (
    title_id, source_dat_id, source_group_ordinal, display_title,
    grouping_status, expected_media_parts, available_media_parts
)
SELECT
    title.id,
    source.dat_id,
    source.group_ordinal,
    source.title_text,
    source.grouping_status,
    source.expected_media_parts,
    source.available_media_parts
FROM derived.source_release source
JOIN catalog.system system
  ON system.source_canonical_system_id = source.canonical_system_id
JOIN catalog.title title
  ON title.system_id = system.id
 AND title.cluster_key = source.title_text
 AND title.grouping_basis = 'exact_title'
ORDER BY source.dat_id, source.group_ordinal;

INSERT INTO catalog.package (
    id, source_dat_id, source_archive_name_id, source_collection, dat_path,
    archive_name, source_tree_path, resolved_path, staged_file_count
)
SELECT package.id, package.dat_id, package.archive_name_id, dat.romset,
    dat.dat_path, archive.archive_name, package.source_tree_path,
    path.resolved_path, package.staged_file_count
FROM derived.package package
JOIN derived.dat dat ON dat.id = package.dat_id
JOIN derived.archive_name archive ON archive.id = package.archive_name_id
LEFT JOIN derived.package_path path ON path.package_id = package.id
WHERE EXISTS (
    SELECT 1 FROM derived.source_release_package membership
    WHERE membership.package_id = package.id
)
ORDER BY package.id;

INSERT INTO catalog.package_file (
    id, package_id, source_full_path, member_path, file_name, size,
    crc_hex, sha1_hex, md5_hex, sha1_verified, md5_verified, crc_verified,
    size_verified, deep_scanned
)
SELECT file.id, file.package_id, file.source_full_path, file.member_path,
    file.file_name, file.size, file.crc_hex, file.sha1_hex, file.md5_hex,
    file.sha1_verified, file.md5_verified, file.crc_verified,
    file.size_verified, file.deep_scanned
FROM derived.file file
JOIN catalog.package package ON package.id = file.package_id
ORDER BY file.id;

INSERT INTO catalog.release_package (
    release_id, package_id, source_archive_name_id, source_record_index,
    media_type, media_part, media_sequence, media_total, media_total_label,
    media_side, media_label, media_description
)
SELECT
    release.id,
    membership.package_id,
    membership.archive_name_id,
    membership.record_index,
    membership.media_type,
    membership.media_part,
    membership.media_sequence,
    membership.media_total,
    membership.media_total_label,
    membership.media_side,
    membership.media_label,
    membership.media_description
FROM derived.source_release_package membership
JOIN catalog.release release
  ON release.source_dat_id = membership.source_dat_id
 AND release.source_group_ordinal = membership.source_group_ordinal
ORDER BY release.id, membership.media_sequence NULLS LAST,
    membership.media_part, membership.media_side, membership.package_id;
