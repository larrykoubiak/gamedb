-- Validate the intentionally small catalog projection and publish it.
CREATE INDEX title_system_display_idx
    ON catalog.title(system_id, display_title);
CREATE INDEX release_title_idx ON catalog.release(title_id);
CREATE INDEX release_grouping_status_idx
    ON catalog.release(grouping_status);
CREATE INDEX package_source_idx
    ON catalog.package(source_collection, archive_name);
CREATE INDEX package_file_package_idx ON catalog.package_file(package_id);
CREATE INDEX package_file_sha1_idx ON catalog.package_file(sha1_hex);
CREATE INDEX release_package_release_order_idx
    ON catalog.release_package(
        release_id, media_sequence NULLS LAST, media_part, media_side
    );
CREATE INDEX release_package_package_idx
    ON catalog.release_package(package_id);

DO $$
DECLARE
    expected_count bigint;
    actual_count bigint;
BEGIN
    SELECT count(*) INTO expected_count
    FROM (
        SELECT canonical_system_id, title_text
        FROM derived.source_release
        GROUP BY canonical_system_id, title_text
    ) exact_titles;
    SELECT count(*) INTO actual_count FROM catalog.title;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog title count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO expected_count FROM derived.source_release;
    SELECT count(*) INTO actual_count FROM catalog.release;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog release count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO expected_count FROM derived.source_release_package;
    SELECT count(*) INTO actual_count FROM catalog.release_package;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog release-package count %, expected %',
            actual_count, expected_count;
    END IF;
END;
$$;

COMMENT ON TABLE catalog.title IS
    'System-scoped browse/search clusters built from derived source titles.';
COMMENT ON TABLE catalog.release IS
    'Consumer projection of source-faithful releases assembled by the deriver.';
COMMENT ON TABLE catalog.package IS
    'Consumer-visible archive and its resolved source location.';
COMMENT ON TABLE catalog.package_file IS
    'Consumer-visible members, hashes, sizes, and verification facts.';
COMMENT ON TABLE catalog.release_package IS
    'Catalog membership connecting releases to consumer-visible packages.';

ANALYZE catalog.system;
ANALYZE catalog.title;
ANALYZE catalog.release;
ANALYZE catalog.package;
ANALYZE catalog.package_file;
ANALYZE catalog.release_package;

COMMIT;
