-- Build the first consumer-facing catalogue from the rebuildable parse layer.
-- Releases are source-faithful: only explicitly numbered media records whose
-- title and every non-media tag agree are grouped automatically.
\set ON_ERROR_STOP on
BEGIN;

CREATE TABLE IF NOT EXISTS ref.path_mapping (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_prefix text NOT NULL UNIQUE,
    target_prefix text NOT NULL,
    CHECK (btrim(source_prefix) <> ''),
    CHECK (btrim(target_prefix) <> ''),
    CHECK (right(source_prefix, 1) <> '/'),
    CHECK (right(target_prefix, 1) <> '/')
);

-- Drop consumers before refreshing the maintained mapping table so this script
-- is independently replayable after a previous catalog build.
DROP SCHEMA IF EXISTS catalog CASCADE;

TRUNCATE ref.path_mapping RESTART IDENTITY;
\copy ref.path_mapping (source_prefix, target_prefix) FROM 'data/reference/path_mappings.csv' WITH (FORMAT csv, HEADER true)

CREATE SCHEMA catalog;

CREATE TABLE catalog.system (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_canonical_system_id bigint NOT NULL UNIQUE
        REFERENCES ref.canonical_system(id) ON DELETE RESTRICT,
    manufacturer_name text NOT NULL,
    system_name text NOT NULL,
    UNIQUE (manufacturer_name, system_name)
);

CREATE TABLE catalog.release (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id bigint NOT NULL REFERENCES catalog.system(id) ON DELETE RESTRICT,
    source_dat_id bigint NOT NULL REFERENCES derived.dat(id) ON DELETE RESTRICT,
    source_group_ordinal integer NOT NULL CHECK (source_group_ordinal > 0),
    display_title text NOT NULL CHECK (btrim(display_title) <> ''),
    grouping_status text NOT NULL CHECK (grouping_status IN (
        'standalone', 'media_singleton', 'media_grouped', 'media_complete',
        'media_ambiguous'
    )),
    expected_media_parts integer CHECK (expected_media_parts > 0),
    available_media_parts integer CHECK (available_media_parts > 0),
    needs_review boolean NOT NULL,
    UNIQUE (source_dat_id, source_group_ordinal)
);

CREATE TABLE catalog.package (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_archive_id bigint NOT NULL UNIQUE
        REFERENCES derived.archive(id) ON DELETE RESTRICT,
    source_collection text NOT NULL,
    source_dat_name text NOT NULL,
    source_dat_path text NOT NULL,
    archive_name text NOT NULL,
    extension text NOT NULL,
    source_tree_path text,
    path_mapping_id bigint REFERENCES ref.path_mapping(id) ON DELETE RESTRICT,
    resolved_path text,
    parse_status text NOT NULL,
    parse_issues text[] NOT NULL,
    staged_file_count bigint NOT NULL CHECK (staged_file_count > 0)
);

CREATE TABLE catalog.release_package (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id bigint NOT NULL REFERENCES catalog.release(id) ON DELETE CASCADE,
    package_id bigint NOT NULL REFERENCES catalog.package(id) ON DELETE RESTRICT,
    source_archive_name_record_id bigint NOT NULL
        REFERENCES derived.archive_name_record(id) ON DELETE RESTRICT,
    record_index integer NOT NULL CHECK (record_index > 0),
    media_type text,
    media_part text,
    media_sequence integer CHECK (media_sequence > 0),
    media_total integer CHECK (media_total > 0),
    media_total_label text,
    media_side text,
    media_label text,
    media_description text,
    parse_status text NOT NULL,
    parse_issues text[] NOT NULL,
    classification_issues text[] NOT NULL,
    UNIQUE (package_id, source_archive_name_record_id)
);

CREATE TABLE catalog.release_attribute (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id bigint NOT NULL REFERENCES catalog.release(id) ON DELETE CASCADE,
    release_package_id bigint NOT NULL
        REFERENCES catalog.release_package(id) ON DELETE CASCADE,
    source_archive_tag_id bigint NOT NULL
        REFERENCES derived.archive_tag(id) ON DELETE RESTRICT,
    tag_index integer NOT NULL CHECK (tag_index > 0),
    category text NOT NULL,
    classification_status text NOT NULL,
    raw_value text NOT NULL,
    identifier text,
    value text,
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
    rule text NOT NULL,
    UNIQUE (release_package_id, tag_index)
);

CREATE TABLE catalog.file (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    package_id bigint NOT NULL REFERENCES catalog.package(id) ON DELETE CASCADE,
    source_run_id uuid NOT NULL,
    source_exported_at timestamptz NOT NULL,
    source_tree_path text NOT NULL,
    source_full_path text NOT NULL,
    member_path text NOT NULL,
    file_name text NOT NULL,
    size bigint,
    crc_hex text,
    sha1_hex text,
    md5_hex text,
    alt_size bigint,
    alt_crc_hex text,
    alt_sha1_hex text,
    alt_md5_hex text,
    sha1_verified boolean,
    md5_verified boolean,
    crc_verified boolean,
    size_verified boolean,
    deep_scanned boolean,
    dat_status integer,
    got_status integer,
    rep_status integer,
    source_game_id text,
    source_game_description text
);

INSERT INTO catalog.system (
    source_canonical_system_id, manufacturer_name, system_name
)
SELECT id, canonical_manufacturer_name, canonical_system_name
FROM ref.canonical_system
ORDER BY canonical_manufacturer_name, canonical_system_name;

-- One candidate is one parsed record as it occurs in one source DAT/archive.
-- The JSON signature intentionally includes every non-media tag, including
-- unknown tags and source order. Automatic grouping is therefore conservative.
CREATE TEMP TABLE _catalog_candidate ON COMMIT DROP AS
SELECT
    a.id AS archive_id,
    r.id AS record_id,
    d.id AS dat_id,
    d.canonical_system_id,
    r.record_index,
    r.title_candidate,
    r.parse_status,
    r.parse_issues,
    r.classification_issues,
    count(t.id) FILTER (WHERE t.category = 'media') AS media_count,
    max(t.details ->> 'type') FILTER (WHERE t.category = 'media') AS media_type,
    max(t.details ->> 'part') FILTER (WHERE t.category = 'media') AS media_part,
    max((t.details ->> 'total')::integer)
        FILTER (WHERE t.category = 'media' AND t.details ? 'total') AS media_total,
    max(t.details ->> 'total_label')
        FILTER (WHERE t.category = 'media') AS media_total_label,
    max(t.details ->> 'side') FILTER (WHERE t.category = 'media') AS media_side,
    max(t.details ->> 'label') FILTER (WHERE t.category = 'media') AS media_label,
    max(t.details ->> 'description')
        FILTER (WHERE t.category = 'media') AS media_description,
    coalesce(
        jsonb_agg(
            jsonb_build_object(
                'index', t.tag_index,
                'raw', t.raw_value,
                'identifier', t.identifier,
                'value', t.value,
                'category', t.category,
                'status', t.classification_status,
                'details', t.details
            ) ORDER BY t.tag_index
        ) FILTER (WHERE t.id IS NOT NULL AND t.category <> 'media'),
        '[]'::jsonb
    ) AS non_media_signature
FROM derived.archive a
JOIN derived.dat d ON d.id = a.dat_id
JOIN derived.archive_name_record r ON r.archive_name_id = a.archive_name_id
LEFT JOIN derived.archive_tag t ON t.archive_name_record_id = r.id
GROUP BY a.id, r.id, d.id, d.canonical_system_id, r.record_index,
    r.title_candidate, r.parse_status, r.parse_issues, r.classification_issues;

CREATE TEMP TABLE _catalog_preliminary ON COMMIT DROP AS
SELECT c.*,
    count(*) OVER preliminary_group AS preliminary_member_count,
    count(*) OVER preliminary_slot AS preliminary_slot_count
FROM _catalog_candidate c
WINDOW
    preliminary_group AS (
        PARTITION BY c.dat_id, c.canonical_system_id, c.title_candidate,
            c.non_media_signature, c.media_type, c.media_total,
            c.media_total_label,
            CASE WHEN c.media_count = 1 AND c.media_part IS NOT NULL
                THEN 0 ELSE c.archive_id END,
            CASE WHEN c.media_count = 1 AND c.media_part IS NOT NULL
                THEN 0 ELSE c.record_id END
    ),
    preliminary_slot AS (
        PARTITION BY c.dat_id, c.canonical_system_id, c.title_candidate,
            c.non_media_signature, c.media_type, c.media_total,
            c.media_total_label,
            CASE WHEN c.media_count = 1 AND c.media_part IS NOT NULL
                THEN c.media_part END,
            coalesce(c.media_side, ''),
            CASE WHEN c.media_count = 1 AND c.media_part IS NOT NULL
                THEN 0 ELSE c.archive_id END,
            CASE WHEN c.media_count = 1 AND c.media_part IS NOT NULL
                THEN 0 ELSE c.record_id END
    );

-- A repeated part/side slot makes the proposed set ambiguous. In that case,
-- split every candidate into its own release rather than risk a false merge.
CREATE TEMP TABLE _catalog_member ON COMMIT DROP AS
SELECT p.*,
    dense_rank() OVER (
        PARTITION BY p.dat_id
        ORDER BY p.title_candidate, p.non_media_signature, p.media_type,
            p.media_total, p.media_total_label,
            CASE
                WHEN p.media_count = 1 AND p.media_part IS NOT NULL
                     AND p.preliminary_slot_count = 1 THEN 0
                ELSE p.archive_id
            END,
            CASE
                WHEN p.media_count = 1 AND p.media_part IS NOT NULL
                     AND p.preliminary_slot_count = 1 THEN 0
                ELSE p.record_id
            END
    ) AS group_ordinal,
    (p.media_count = 1 AND p.media_part IS NOT NULL
        AND p.preliminary_slot_count > 1) AS ambiguous_slot
FROM _catalog_preliminary p;

INSERT INTO catalog.release (
    system_id, source_dat_id, source_group_ordinal, display_title,
    grouping_status, expected_media_parts, available_media_parts, needs_review
)
SELECT
    s.id,
    m.dat_id,
    m.group_ordinal,
    min(m.title_candidate),
    CASE
        WHEN bool_or(m.ambiguous_slot) THEN 'media_ambiguous'
        WHEN bool_and(m.media_count = 1 AND m.media_part IS NOT NULL)
             AND count(*) > 1
             AND min(m.media_total) IS NOT NULL
             AND bool_and(m.media_part ~ '^0*[1-9][0-9]*$')
             AND count(DISTINCT m.media_part::integer)
                 FILTER (WHERE m.media_part ~ '^0*[1-9][0-9]*$') = min(m.media_total)
             AND min(m.media_part::integer)
                 FILTER (WHERE m.media_part ~ '^0*[1-9][0-9]*$') = 1
             AND max(m.media_part::integer)
                 FILTER (WHERE m.media_part ~ '^0*[1-9][0-9]*$') = min(m.media_total)
            THEN 'media_complete'
        WHEN bool_and(m.media_count = 1 AND m.media_part IS NOT NULL)
             AND count(*) > 1 THEN 'media_grouped'
        WHEN bool_and(m.media_count = 1 AND m.media_part IS NOT NULL)
            THEN 'media_singleton'
        ELSE 'standalone'
    END,
    CASE WHEN bool_and(m.media_count = 1 AND m.media_part IS NOT NULL)
        THEN min(m.media_total) END,
    CASE WHEN bool_and(m.media_count = 1 AND m.media_part IS NOT NULL)
        THEN count(DISTINCT m.media_part) END,
    bool_or(
        m.parse_status = 'review'
        OR cardinality(m.classification_issues) > 0
        OR m.ambiguous_slot
    )
FROM _catalog_member m
JOIN catalog.system s
  ON s.source_canonical_system_id = m.canonical_system_id
GROUP BY s.id, m.dat_id, m.group_ordinal
ORDER BY m.dat_id, m.group_ordinal;

INSERT INTO catalog.package (
    source_archive_id, source_collection, source_dat_name, source_dat_path,
    archive_name, extension, parse_status, parse_issues, staged_file_count
)
SELECT a.id, d.romset, d.dat_name, d.dat_path, n.archive_name, n.extension,
    n.parse_status, n.parse_issues, a.staged_row_count
FROM derived.archive a
JOIN derived.dat d ON d.id = a.dat_id
JOIN derived.archive_name n ON n.id = a.archive_name_id
ORDER BY a.id;

INSERT INTO catalog.release_package (
    release_id, package_id, source_archive_name_record_id, record_index,
    media_type, media_part, media_sequence, media_total, media_total_label,
    media_side, media_label, media_description, parse_status, parse_issues,
    classification_issues
)
SELECT rel.id, p.id, m.record_id, m.record_index,
    m.media_type, m.media_part,
    CASE WHEN m.media_part ~ '^0*[1-9][0-9]*$' THEN m.media_part::integer END,
    m.media_total, m.media_total_label, m.media_side, m.media_label,
    m.media_description, m.parse_status, m.parse_issues,
    m.classification_issues
FROM _catalog_member m
JOIN catalog.release rel
  ON rel.source_dat_id = m.dat_id
 AND rel.source_group_ordinal = m.group_ordinal
JOIN catalog.package p ON p.source_archive_id = m.archive_id
ORDER BY rel.id,
    CASE WHEN m.media_part ~ '^0*[1-9][0-9]*$' THEN m.media_part::integer END
        NULLS LAST,
    m.media_part, m.media_side, p.id, m.record_index;

INSERT INTO catalog.release_attribute (
    release_id, release_package_id, source_archive_tag_id, tag_index, category,
    classification_status, raw_value, identifier, value, details, rule
)
SELECT rp.release_id, rp.id, t.id, t.tag_index, t.category,
    t.classification_status, t.raw_value, t.identifier, t.value, t.details, t.rule
FROM catalog.release_package rp
JOIN derived.archive_tag t
  ON t.archive_name_record_id = rp.source_archive_name_record_id
ORDER BY rp.id, t.tag_index;

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

CREATE INDEX release_system_title_idx
    ON catalog.release(system_id, display_title);
CREATE INDEX release_review_idx
    ON catalog.release(needs_review) WHERE needs_review;
CREATE INDEX release_grouping_status_idx
    ON catalog.release(grouping_status);
CREATE INDEX package_collection_idx
    ON catalog.package(source_collection);
CREATE INDEX package_resolved_path_idx
    ON catalog.package(resolved_path) WHERE resolved_path IS NOT NULL;
CREATE INDEX release_package_release_order_idx
    ON catalog.release_package(
        release_id, media_sequence NULLS LAST, media_part, media_side
    );
CREATE INDEX release_package_package_idx
    ON catalog.release_package(package_id);
CREATE INDEX release_attribute_release_category_idx
    ON catalog.release_attribute(release_id, category);
CREATE INDEX release_attribute_unknown_idx
    ON catalog.release_attribute(classification_status)
    WHERE classification_status = 'unclassified';
CREATE INDEX file_package_idx ON catalog.file(package_id);
CREATE INDEX file_sha1_idx ON catalog.file(sha1_hex) WHERE sha1_hex IS NOT NULL;
CREATE INDEX file_md5_idx ON catalog.file(md5_hex) WHERE md5_hex IS NOT NULL;
CREATE INDEX file_crc_size_idx ON catalog.file(crc_hex, size)
    WHERE crc_hex IS NOT NULL;

DO $$
DECLARE
    expected_count bigint;
    actual_count bigint;
BEGIN
    SELECT count(*) INTO expected_count FROM derived.archive;
    SELECT count(*) INTO actual_count FROM catalog.package;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog package count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO expected_count FROM _catalog_member;
    SELECT count(*) INTO actual_count FROM catalog.release_package;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog release-package count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT sum(staged_file_count) INTO expected_count FROM catalog.package;
    SELECT count(*) INTO actual_count FROM catalog.file;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog file count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM catalog.package
    WHERE source_tree_path IS NULL
       OR (path_mapping_id IS NULL) <> (resolved_path IS NULL);
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% catalog packages have invalid path resolution',
            actual_count;
    END IF;
END;
$$;

COMMENT ON TABLE catalog.release IS
    'Consumer-facing source releases; explicit media parts are grouped only by exact non-media agreement.';
COMMENT ON TABLE catalog.package IS
    'Source archive/package provenance, including optional physical path resolution.';
COMMENT ON TABLE catalog.release_package IS
    'Many-to-many release/package membership, including parsed media ordering.';
COMMENT ON TABLE catalog.release_attribute IS
    'Lossless classified and unclassified source tags attached through their originating package record.';
COMMENT ON TABLE catalog.file IS
    'RomVault file observations and content hashes belonging to a source package.';

ANALYZE catalog.system;
ANALYZE catalog.release;
ANALYZE catalog.package;
ANALYZE catalog.release_package;
ANALYZE catalog.release_attribute;
ANALYZE catalog.file;

COMMIT;
