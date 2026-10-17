-- Project external metadata only after software identity is stable. The raw
-- RDB snapshot remains staging-owned; this layer publishes attributed values.
\set ON_ERROR_STOP on
BEGIN;

DROP TABLE IF EXISTS catalog.software_fact_evidence;
DROP TABLE IF EXISTS catalog.software_fact;

CREATE TABLE catalog.software_fact (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    software_id bigint NOT NULL
        REFERENCES catalog.software(id) ON DELETE CASCADE,
    fact_key text NOT NULL CHECK (fact_key IN (
        'description', 'developer', 'publisher', 'genre', 'franchise',
        'player_count', 'rumble', 'analog', 'enhancement_hardware',
        'tags', 'origin'
    )),
    fact_value text NOT NULL CHECK (btrim(fact_value) <> ''),
    source_provider text NOT NULL CHECK (source_provider = 'libretro-database'),
    source_revision text NOT NULL
        CHECK (source_revision ~ '^[0-9a-f]{40}$'),
    source_record_count bigint NOT NULL CHECK (source_record_count > 0),
    matched_content_count bigint NOT NULL CHECK (matched_content_count > 0),
    value_rank bigint NOT NULL CHECK (value_rank > 0),
    value_count bigint NOT NULL CHECK (value_count > 0),
    UNIQUE (
        software_id, fact_key, fact_value, source_provider, source_revision
    ),
    CHECK (matched_content_count <= source_record_count),
    CHECK (value_rank <= value_count)
);

CREATE TABLE catalog.software_fact_evidence (
    software_fact_id bigint NOT NULL
        REFERENCES catalog.software_fact(id) ON DELETE CASCADE,
    source_file_id bigint NOT NULL,
    source_row_number bigint NOT NULL CHECK (source_row_number > 0),
    source_database text NOT NULL CHECK (btrim(source_database) <> ''),
    source_relative_path text NOT NULL CHECK (btrim(source_relative_path) <> ''),
    matched_sha1 text NOT NULL CHECK (matched_sha1 ~ '^[0-9a-f]{40}$'),
    PRIMARY KEY (software_fact_id, source_file_id, source_row_number)
);

-- A catalog rebuild is valid before the optional RDB source has been imported.
SELECT (
    to_regclass('staging.libretro_rdb_import') IS NOT NULL
    AND to_regclass('staging.libretro_rdb_file') IS NOT NULL
    AND to_regclass('staging.libretro_rdb_entry') IS NOT NULL
) AS has_libretro_rdb
\gset
