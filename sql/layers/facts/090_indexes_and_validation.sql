-- Validate and publish normalized facts. _catalog_source_fact is scratch state
-- produced inside this layer's transaction by 020_build.sql.
CREATE INDEX release_fact_key_value_idx
    ON catalog.release_fact(fact_key, fact_value, release_id);
CREATE INDEX release_fact_evidence_package_idx
    ON catalog.release_fact_evidence(release_package_id);
CREATE INDEX release_fact_evidence_source_tag_idx
    ON catalog.release_fact_evidence(source_archive_tag_id);

DO $$
DECLARE
    expected_count bigint;
    actual_count bigint;
BEGIN
    SELECT count(*) INTO expected_count FROM _catalog_source_fact;
    SELECT count(*) INTO actual_count FROM catalog.release_fact_evidence;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog release-fact evidence count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM catalog.release_fact f
    WHERE f.origin = 'source_tag'
      AND NOT EXISTS (
          SELECT 1
          FROM catalog.release_fact_evidence evidence
          WHERE evidence.release_fact_id = f.id
      );
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% source-tag release facts have no evidence',
            actual_count;
    END IF;
END;
$$;

COMMENT ON TABLE catalog.release_fact IS
    'Deduplicated normalized release features from explicit source tags or catalog structure.';
COMMENT ON TABLE catalog.release_fact_evidence IS
    'Source package/tag evidence supporting a normalized release fact.';
COMMENT ON VIEW catalog.release_source_attribute IS
    'Auditable source-shaped classified and unclassified tags without catalog duplication.';

ANALYZE catalog.release_fact;
ANALYZE catalog.release_fact_evidence;

COMMIT;
