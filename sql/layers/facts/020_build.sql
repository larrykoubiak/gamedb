-- Assertions are already normalized by Python; this layer only deduplicates
-- them across packages belonging to the same assembled release.
INSERT INTO catalog.release_fact (
    release_id, fact_key, fact_value, origin, confidence
)
SELECT DISTINCT
    membership.release_id,
    assertion.assertion_key,
    assertion.assertion_value,
    'source_tag',
    'explicit'
FROM catalog.release_package membership
JOIN derived.assertion assertion
  ON assertion.archive_name_id = membership.source_archive_name_id
 AND assertion.record_index = membership.source_record_index
ORDER BY membership.release_id, assertion.assertion_key,
    assertion.assertion_value;

INSERT INTO catalog.release_fact (
    release_id, fact_key, fact_value, origin, confidence
)
SELECT release.id, 'source_collection', dat.romset, 'catalog', 'computed'
FROM catalog.release release
JOIN derived.dat dat ON dat.id = release.source_dat_id
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
    release_fact_id, release_package_id, source_assertion_id
)
SELECT fact.id, membership.id, assertion.id
FROM catalog.release_package membership
JOIN derived.assertion assertion
  ON assertion.archive_name_id = membership.source_archive_name_id
 AND assertion.record_index = membership.source_record_index
JOIN catalog.release_fact fact
  ON fact.release_id = membership.release_id
 AND fact.fact_key = assertion.assertion_key
 AND fact.fact_value = assertion.assertion_value
 AND fact.origin = 'source_tag'
ORDER BY fact.id, membership.id, assertion.id;
