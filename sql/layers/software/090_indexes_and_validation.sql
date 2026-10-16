CREATE INDEX software_system_name_idx
    ON catalog.software(system_id, display_name);
CREATE INDEX software_preferred_title_idx
    ON catalog.software(preferred_title_id);
CREATE INDEX software_release_software_idx
    ON catalog.software_release(software_id, release_id);
CREATE INDEX software_release_basis_idx
    ON catalog.software_release(assignment_basis);
CREATE INDEX software_evidence_software_idx
    ON _software_release_evidence(software_id, release_id);
CREATE INDEX software_evidence_sha1_idx
    ON _software_release_evidence(sha1_hex);
CREATE INDEX software_candidate_status_idx
    ON _software_identity_candidate(
        review_status, candidate_type, system_id
    );

DO $$
DECLARE
    expected_count bigint;
    actual_count bigint;
BEGIN
    SELECT count(*) INTO expected_count FROM catalog.release;
    SELECT count(*) INTO actual_count FROM catalog.software_release;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog software membership count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM catalog.software_release membership
    JOIN catalog.software software ON software.id = membership.software_id
    JOIN catalog.release release ON release.id = membership.release_id
    JOIN catalog.title title ON title.id = release.title_id
    WHERE software.system_id <> title.system_id
       OR (membership.assignment_basis = 'exact_sha1'
            AND software.identity_basis <> 'recovered_legacy')
       OR (membership.assignment_basis = 'parent_clone'
            AND software.identity_basis NOT IN (
                'recovered_legacy', 'parent_clone'
            ))
       OR (membership.assignment_basis = 'manual_override'
            AND software.identity_basis <> 'manual')
       OR (membership.assignment_basis = 'title_fallback'
            AND software.identity_basis <> 'title_fallback');
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% software memberships violate identity boundaries',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM catalog.software software
    JOIN catalog.title title ON title.id = software.preferred_title_id
    WHERE software.system_id <> title.system_id;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% software display titles cross system boundaries',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM (
        SELECT membership.release_id
        FROM catalog.software_release membership
        LEFT JOIN _software_release_evidence evidence
          ON evidence.software_id = membership.software_id
         AND evidence.release_id = membership.release_id
        GROUP BY membership.release_id, membership.assignment_basis,
            membership.evidence_match_count
        HAVING (membership.assignment_basis <> 'title_fallback'
                AND count(evidence.id) <> membership.evidence_match_count)
            OR (membership.assignment_basis = 'title_fallback'
                AND count(evidence.id) <> 0)
    ) invalid_evidence;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% software memberships disagree with their evidence',
            actual_count;
    END IF;
END;
$$;

COMMENT ON TABLE catalog.software IS
    'Platform-specific playable products recovered from historical evidence, with explicit title-based fallbacks.';
COMMENT ON TABLE catalog.software_release IS
    'Total assignment of every current release to one software identity and its assignment basis.';
COMMENT ON TABLE _software_release_evidence IS
    'Typed hash, Parent/Clone, translation-member, anchored-title, or manual evidence supporting software assignments.';
COMMENT ON TABLE _software_identity_candidate IS
    'Conflicting generated relationships and recovered positive/negative human reviews retained for reconciliation.';

ANALYZE catalog.software;
ANALYZE catalog.software_release;
ANALYZE _software_release_evidence;
ANALYZE _software_identity_candidate;

COMMIT;
