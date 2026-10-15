-- Validate and publish the core catalog transaction opened by
-- 010_schema_and_releases.sql. Temporary tables here are private to this layer.
CREATE INDEX title_system_display_idx
    ON catalog.title(system_id, display_title);
CREATE INDEX title_review_idx
    ON catalog.title(needs_review) WHERE needs_review;
CREATE INDEX release_title_idx ON catalog.release(title_id);
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
    SELECT count(*) INTO expected_count
    FROM (
        SELECT canonical_system_id, title_candidate
        FROM _catalog_member
        GROUP BY canonical_system_id, title_candidate
    ) exact_titles;
    SELECT count(*) INTO actual_count
    FROM catalog.title
    WHERE grouping_basis = 'exact_title';
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog exact-title count %, expected %',
            actual_count, expected_count;
    END IF;

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
COMMENT ON TABLE catalog.title IS
    'System-scoped browse/search clusters; exact-title grouping is not proof of shared software identity.';
COMMENT ON TABLE catalog.package IS
    'Source archive/package provenance, including optional physical path resolution.';
COMMENT ON TABLE catalog.release_package IS
    'Many-to-many release/package membership, including parsed media ordering.';
COMMENT ON TABLE catalog.file IS
    'RomVault file observations and content hashes belonging to a source package.';

ANALYZE catalog.system;
ANALYZE catalog.title;
ANALYZE catalog.release;
ANALYZE catalog.package;
ANALYZE catalog.release_package;
ANALYZE catalog.file;

COMMIT;
