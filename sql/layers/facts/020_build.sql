-- Project classified source attributes into normalized release facts and retain
-- their package/tag evidence. One source tag
-- can yield several facts (for example, En,Fr), while identical facts repeated
-- by several media packages collapse to one release-level row.
CREATE TEMP TABLE _catalog_source_fact ON COMMIT DROP AS
SELECT DISTINCT release_id, release_package_id, source_archive_tag_id,
    fact_key, fact_value
FROM (
    SELECT rp.release_id, rp.id AS release_package_id,
        t.id AS source_archive_tag_id, t.category AS fact_key,
        code.value AS fact_value
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    CROSS JOIN LATERAL jsonb_array_elements_text(t.details -> 'codes') code(value)
    WHERE t.classification_status = 'classified'
      AND t.category IN ('region', 'language')

    UNION ALL

    SELECT rp.release_id, rp.id, t.id, 'language', code.value
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    CROSS JOIN LATERAL
        jsonb_array_elements_text(t.details -> 'language_codes') code(value)
    WHERE t.classification_status = 'classified'
      AND t.category = 'dump_modification'
      AND t.details ->> 'code' = 'translated'

    UNION ALL

    SELECT rp.release_id, rp.id, t.id, 'version', t.details ->> 'version'
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    WHERE t.classification_status = 'classified'
      AND t.category = 'dump_modification'
      AND t.details ->> 'code' = 'translated'
      AND nullif(btrim(t.details ->> 'version'), '') IS NOT NULL

    UNION ALL

    SELECT rp.release_id, rp.id, t.id, t.category, t.details ->> 'code'
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    WHERE t.classification_status = 'classified'
      AND t.category IN (
          'release_status', 'demo', 'copyright_status', 'license', 'special',
          'distribution_channel', 'dump_modification', 'dump_status'
      )
      AND nullif(btrim(t.details ->> 'code'), '') IS NOT NULL

    UNION ALL

    SELECT rp.release_id, rp.id, t.id, t.category, t.details ->> 'text'
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    WHERE t.classification_status = 'classified'
      AND t.category IN (
          'version', 'revision', 'release_date', 'publisher',
          'system_requirement', 'video', 'media_label'
      )
      AND nullif(btrim(t.details ->> 'text'), '') IS NOT NULL

    UNION ALL

    SELECT rp.release_id, rp.id, t.id, 'language_count',
        t.details ->> 'count'
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    WHERE t.classification_status = 'classified'
      AND t.category = 'language'
      AND t.details ? 'count'

    UNION ALL

    SELECT rp.release_id, rp.id, t.id, 'bios', 'true'
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    WHERE t.classification_status = 'classified'
      AND t.category = 'bios'

    UNION ALL

    SELECT rp.release_id, rp.id, t.id, t.category, 'unknown'
    FROM catalog.release_package rp
    JOIN derived.archive_tag t
      ON t.archive_name_record_id = rp.source_archive_name_record_id
    WHERE t.classification_status = 'classified'
      AND t.category IN ('region', 'publisher')
      AND coalesce((t.details ->> 'unknown')::boolean, false)
) normalized
WHERE nullif(btrim(fact_value), '') IS NOT NULL;

INSERT INTO catalog.release_fact (
    release_id, fact_key, fact_value, origin, confidence
)
SELECT DISTINCT release_id, fact_key, fact_value, 'source_tag', 'explicit'
FROM _catalog_source_fact
ORDER BY release_id, fact_key, fact_value;

INSERT INTO catalog.release_fact (
    release_id, fact_key, fact_value, origin, confidence
)
SELECT r.id, 'source_collection', d.romset, 'catalog', 'computed'
FROM catalog.release r
JOIN derived.dat d ON d.id = r.source_dat_id
UNION ALL
SELECT id, 'media_status',
    CASE grouping_status
        WHEN 'media_singleton' THEN 'singleton'
        WHEN 'media_grouped' THEN 'grouped'
        WHEN 'media_complete' THEN 'complete'
        WHEN 'media_ambiguous' THEN 'ambiguous'
        ELSE 'standalone'
    END,
    'catalog', 'computed'
FROM catalog.release
UNION ALL
SELECT id, 'review_status',
    CASE WHEN needs_review THEN 'needs_review' ELSE 'ready' END,
    'catalog', 'computed'
FROM catalog.release
ORDER BY 1, 2;

INSERT INTO catalog.release_fact_evidence (
    release_fact_id, release_package_id, source_archive_tag_id
)
SELECT f.id, source.release_package_id, source.source_archive_tag_id
FROM _catalog_source_fact source
JOIN catalog.release_fact f
  ON f.release_id = source.release_id
 AND f.fact_key = source.fact_key
 AND f.fact_value = source.fact_value
 AND f.origin = 'source_tag'
ORDER BY f.id, source.release_package_id, source.source_archive_tag_id;
