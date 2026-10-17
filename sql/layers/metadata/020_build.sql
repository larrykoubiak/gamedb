\if :has_libretro_rdb

CREATE TEMP TABLE _current_libretro_import ON COMMIT DROP AS
SELECT id, source_revision
FROM staging.libretro_rdb_import
ORDER BY imported_at DESC, id DESC
LIMIT 1;

-- A package file can fan out to several source records. Accept a content hash
-- only when every current occurrence ultimately resolves to one software.
CREATE TEMP TABLE _unambiguous_content_software ON COMMIT DROP AS
SELECT package_file.sha1_hex,
    min(software_release.software_id) AS software_id
FROM catalog.package_file package_file
JOIN catalog.release_package release_package
  ON release_package.package_id = package_file.package_id
JOIN catalog.software_release software_release
  ON software_release.release_id = release_package.release_id
WHERE package_file.sha1_hex IS NOT NULL
GROUP BY package_file.sha1_hex
HAVING count(DISTINCT software_release.software_id) = 1;

CREATE UNIQUE INDEX _unambiguous_content_software_sha1_idx
    ON _unambiguous_content_software(sha1_hex);

CREATE TEMP TABLE _libretro_software_claim ON COMMIT DROP AS
SELECT DISTINCT
    matched.software_id,
    mapped.fact_key,
    btrim(mapped.fact_value) AS fact_value,
    source_import.source_revision,
    entry.file_id AS source_file_id,
    entry.row_number AS source_row_number,
    source_file.database_name AS source_database,
    source_file.relative_path AS source_relative_path,
    entry.sha1_hex AS matched_sha1
FROM _current_libretro_import source_import
JOIN staging.libretro_rdb_file source_file
  ON source_file.import_id = source_import.id
JOIN staging.libretro_rdb_entry entry
  ON entry.file_id = source_file.id
JOIN _unambiguous_content_software matched
  ON matched.sha1_hex = entry.sha1_hex
CROSS JOIN LATERAL (
    VALUES
        ('description', entry.raw_record ->> 'description'),
        ('developer', entry.raw_record ->> 'developer'),
        ('publisher', entry.raw_record ->> 'publisher'),
        ('genre', entry.raw_record ->> 'genre'),
        ('franchise', entry.raw_record ->> 'franchise'),
        ('player_count', entry.raw_record ->> 'users'),
        ('rumble', entry.raw_record ->> 'rumble'),
        ('analog', entry.raw_record ->> 'analog'),
        ('enhancement_hardware', entry.raw_record ->> 'enhancement_hw'),
        ('tags', entry.raw_record ->> 'tags'),
        ('origin', entry.raw_record ->> 'origin')
) mapped(fact_key, fact_value)
WHERE nullif(btrim(mapped.fact_value), '') IS NOT NULL;

CREATE INDEX _libretro_software_claim_fact_idx
    ON _libretro_software_claim(software_id, fact_key, fact_value);

WITH aggregated AS (
    SELECT
        software_id,
        fact_key,
        fact_value,
        source_revision,
        count(*) AS source_record_count,
        count(DISTINCT matched_sha1) AS matched_content_count
    FROM _libretro_software_claim
    GROUP BY software_id, fact_key, fact_value, source_revision
), ranked AS (
    SELECT aggregated.*,
        dense_rank() OVER (
            PARTITION BY software_id, fact_key
            ORDER BY matched_content_count DESC, source_record_count DESC
        ) AS value_rank,
        count(*) OVER (
            PARTITION BY software_id, fact_key
        ) AS value_count
    FROM aggregated
)
INSERT INTO catalog.software_fact (
    software_id, fact_key, fact_value, source_provider, source_revision,
    source_record_count, matched_content_count, value_rank, value_count
)
SELECT
    software_id, fact_key, fact_value, 'libretro-database', source_revision,
    source_record_count, matched_content_count, value_rank, value_count
FROM ranked
ORDER BY software_id, fact_key, value_rank, lower(fact_value), fact_value;

INSERT INTO catalog.software_fact_evidence (
    software_fact_id, source_file_id, source_row_number, source_database,
    source_relative_path, matched_sha1
)
SELECT
    fact.id, claim.source_file_id, claim.source_row_number,
    claim.source_database, claim.source_relative_path, claim.matched_sha1
FROM _libretro_software_claim claim
JOIN catalog.software_fact fact
  ON fact.software_id = claim.software_id
 AND fact.fact_key = claim.fact_key
 AND fact.fact_value = claim.fact_value
 AND fact.source_provider = 'libretro-database'
 AND fact.source_revision = claim.source_revision
ORDER BY fact.id, claim.source_file_id, claim.source_row_number;

\endif
