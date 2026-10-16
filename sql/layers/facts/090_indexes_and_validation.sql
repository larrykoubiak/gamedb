CREATE INDEX release_fact_key_value_idx
    ON catalog.release_fact(fact_key, fact_value, release_id);
CREATE INDEX release_fact_evidence_package_idx
    ON _release_fact_evidence(release_package_id);
CREATE INDEX release_fact_evidence_assertion_idx
    ON _release_fact_evidence(source_assertion_id);

DO $$
DECLARE actual_count bigint;
BEGIN
    SELECT count(*) INTO actual_count
    FROM catalog.release_fact fact
    WHERE fact.origin = 'source_tag'
      AND NOT EXISTS (
          SELECT 1
          FROM _release_fact_evidence evidence
          WHERE evidence.release_fact_id = fact.id
      );
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% source-tag release facts have no evidence',
            actual_count;
    END IF;
END;
$$;

COMMENT ON TABLE catalog.release_fact IS
    'Release-level deduplication of typed derived assertions and catalog structure.';
COMMENT ON TABLE _release_fact_evidence IS
    'Derived assertion and package evidence supporting a release fact.';
ANALYZE catalog.release_fact;
ANALYZE _release_fact_evidence;

COMMIT;
