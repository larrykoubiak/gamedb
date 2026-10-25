CREATE INDEX software_fact_key_rank_idx
    ON catalog.software_fact(
        software_id, fact_key, value_rank, matched_content_count DESC, id
    );
CREATE INDEX software_fact_value_idx
    ON catalog.software_fact(fact_key, md5(fact_value), software_id);
CREATE INDEX software_fact_evidence_source_idx
    ON catalog.software_fact_evidence(source_file_id, source_row_number);
CREATE INDEX software_fact_evidence_sha1_idx
    ON catalog.software_fact_evidence(matched_sha1);

DO $$
DECLARE
    invalid_count bigint;
BEGIN
    SELECT count(*) INTO invalid_count
    FROM catalog.software_fact fact
    WHERE fact.source_record_count <> (
        SELECT count(*)
        FROM catalog.software_fact_evidence evidence
        WHERE evidence.software_fact_id = fact.id
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software facts disagree with their evidence count',
            invalid_count;
    END IF;

    SELECT count(*) INTO invalid_count
    FROM (
        SELECT software_id, fact_key
        FROM catalog.software_fact
        GROUP BY software_id, fact_key
        HAVING min(value_rank) <> 1
           OR min(value_count) <> count(*)
           OR max(value_count) <> count(*)
    ) invalid_rank;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software fact groups have invalid ranks or counts',
            invalid_count;
    END IF;
END;
$$;

COMMENT ON TABLE catalog.software_fact IS
    'Attributed software-level metadata candidates from exact-content Libretro and selected LaunchBox title matches.';
COMMENT ON TABLE catalog.software_fact_evidence IS
    'Source rows and matching evidence: source_file_id is an RDB file ID or LaunchBox import ID, scoped by fact provider.';

ANALYZE catalog.software_fact;
ANALYZE catalog.software_fact_evidence;

COMMIT;
