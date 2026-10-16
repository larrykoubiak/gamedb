-- Validate and publish exact-content identity. Temporary component tables are
-- private to this layer's transaction.
CREATE INDEX title_alias_preferred_idx
    ON catalog.title_alias(preferred_title_id);
CREATE INDEX title_content_match_left_title_idx
    ON _title_content_match(left_title_id);
CREATE INDEX title_content_match_right_title_idx
    ON _title_content_match(right_title_id);

DO $$
DECLARE
    expected_count bigint;
    actual_count bigint;
BEGIN
    SELECT count(*) INTO actual_count
    FROM catalog.release_content_signature signature
    JOIN (
        SELECT release_id, count(*)::integer AS package_count
        FROM catalog.release_package
        GROUP BY release_id
    ) actual USING (release_id)
    WHERE signature.package_count <> actual.package_count;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% release content signatures omit packages',
            actual_count;
    END IF;

    SELECT count(*) INTO expected_count FROM _catalog_title_content_match;
    SELECT count(*) INTO actual_count FROM _title_content_match;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog title-content match count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO expected_count
    FROM _catalog_title_component component
    JOIN _catalog_title_representative representative USING (component_id)
    WHERE component.title_id <> representative.preferred_title_id;
    SELECT count(*) INTO actual_count FROM catalog.title_alias;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog title-alias count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM _catalog_title_component component
    JOIN _catalog_title_representative representative USING (component_id)
    JOIN _catalog_title_component_summary summary USING (component_id)
    LEFT JOIN catalog.title_alias alias
      ON alias.alias_title_id = component.title_id
    WHERE component.title_id <> representative.preferred_title_id
      AND (
          alias.preferred_title_id IS DISTINCT FROM representative.preferred_title_id
          OR alias.component_title_count IS DISTINCT FROM summary.component_title_count
          OR alias.evidence_pair_count IS DISTINCT FROM summary.evidence_pair_count
      );
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% catalog title aliases disagree with content components',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM catalog.title_alias alias
    JOIN catalog.title source ON source.id = alias.alias_title_id
    JOIN catalog.title preferred ON preferred.id = alias.preferred_title_id
    WHERE source.system_id <> preferred.system_id;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% catalog title aliases cross system boundaries',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM _title_content_match match
    JOIN catalog.release left_release ON left_release.id = match.left_release_id
    JOIN catalog.release right_release ON right_release.id = match.right_release_id
    JOIN catalog.release_content_signature left_signature
      ON left_signature.release_id = match.left_release_id
    JOIN catalog.release_content_signature right_signature
      ON right_signature.release_id = match.right_release_id
    WHERE left_release.title_id <> match.left_title_id
       OR right_release.title_id <> match.right_title_id
       OR left_signature.rom_count <> match.matched_rom_count
       OR right_signature.rom_count <> match.matched_rom_count
       OR left_signature.package_count <> right_signature.package_count
       OR left_signature.sha1_set_digest <> match.sha1_set_digest
       OR right_signature.sha1_set_digest <> match.sha1_set_digest;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% catalog title-content matches have invalid signatures',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM catalog.title_alias alias
    JOIN catalog.title_alias preferred_alias
      ON preferred_alias.alias_title_id = alias.preferred_title_id;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% catalog title aliases point to another alias',
            actual_count;
    END IF;
END;
$$;

COMMENT ON TABLE catalog.title_alias IS
    'Rebuildable mapping from each non-representative title in an exact-content component to its preferred title.';
COMMENT ON TABLE _title_content_match IS
    'Direct same-system complete-release SHA-1 matches used to build transitive title components.';
COMMENT ON TABLE catalog.package_content_signature IS
    'Complete ordered-multiset digest of SHA-1 ROM members for an unshared package; known auxiliary-only POK files are excluded.';
COMMENT ON TABLE catalog.release_content_signature IS
    'Complete ordered-multiset digest of every eligible package signature in a release.';

ANALYZE catalog.title_alias;
ANALYZE _title_content_match;
ANALYZE catalog.package_content_signature;
ANALYZE catalog.release_content_signature;

COMMIT;
