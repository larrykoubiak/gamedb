WITH scored AS MATERIALIZED (
    SELECT
        score.release_id,
        score.score,
        score.rank_within_software,
        score.breakdown,
        (preferred.release_id = score.release_id) AS selected,
        release.display_title AS source_title,
        membership.assignment_basis,
        membership.evidence_match_count,
        signature.sha1_set_digest AS release_content_signature
    FROM app.user_release_score score
    JOIN app.app_user user_account ON user_account.id = score.user_id
    JOIN catalog.release release ON release.id = score.release_id
    JOIN catalog.software_release membership
      ON membership.release_id = score.release_id
     AND membership.software_id = score.software_id
    LEFT JOIN catalog.release_content_signature signature
      ON signature.release_id = score.release_id
    JOIN app.user_preferred_release preferred
     ON preferred.user_id = score.user_id
     AND preferred.software_id = score.software_id
    WHERE user_account.username = __USERNAME__
      AND score.software_id = __SOFTWARE_ID__
),
release_rows AS (
    SELECT
        scored.*,
        facts.languages,
        facts.regions,
        facts.revisions,
        facts.versions,
        facts.release_dates,
        facts.dump_modifications,
        facts.dump_statuses,
        packages.items AS packages
    FROM scored
    LEFT JOIN LATERAL (
        SELECT
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'language'), '[]'::jsonb) AS languages,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'region'), '[]'::jsonb) AS regions,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'revision'), '[]'::jsonb) AS revisions,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'version'), '[]'::jsonb) AS versions,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'release_date'), '[]'::jsonb) AS release_dates,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'dump_modification'), '[]'::jsonb) AS dump_modifications,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'dump_status'), '[]'::jsonb) AS dump_statuses
        FROM catalog.release_fact f
        WHERE f.release_id = scored.release_id
    ) facts ON true
    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_agg(
            jsonb_build_object(
                'sourceCollection', package.source_collection,
                'archiveName', package.archive_name,
                'sourcePath', package.source_tree_path,
                'resolvedPath', package.resolved_path,
                'contentSignature', signature.sha1_set_digest,
                'files', files.items
            ) ORDER BY release_package.media_sequence NULLS LAST,
                package.archive_name, package.id
        ), '[]'::jsonb) AS items
        FROM catalog.release_package release_package
        JOIN catalog.package package ON package.id = release_package.package_id
        LEFT JOIN catalog.package_content_signature signature
          ON signature.package_id = package.id
        LEFT JOIN LATERAL (
            SELECT coalesce(jsonb_agg(
                jsonb_build_object(
                    'name', file.file_name,
                    'memberPath', file.member_path,
                    'size', file.size,
                    'sha1', file.sha1_hex,
                    'crc', file.crc_hex
                ) ORDER BY file.member_path, file.id
            ), '[]'::jsonb) AS items
            FROM catalog.package_file file
            WHERE file.package_id = package.id
        ) files ON true
        WHERE release_package.release_id = scored.release_id
    ) packages ON true
)
SELECT coalesce(jsonb_agg(
    jsonb_build_object(
        'sourceTitle', release_rows.source_title,
        'releaseContentSignature', release_rows.release_content_signature,
        'assignmentBasis', release_rows.assignment_basis,
        'evidenceMatchCount', release_rows.evidence_match_count,
        'score', release_rows.score,
        'rank', release_rows.rank_within_software,
        'breakdown', release_rows.breakdown,
        'selected', release_rows.selected,
        'languages', release_rows.languages,
        'regions', release_rows.regions,
        'revisions', release_rows.revisions,
        'versions', release_rows.versions,
        'releaseDates', release_rows.release_dates,
        'dumpModifications', release_rows.dump_modifications,
        'dumpStatuses', release_rows.dump_statuses,
        'packages', release_rows.packages
    ) ORDER BY release_rows.rank_within_software,
        release_rows.score DESC, release_rows.release_id
), '[]'::jsonb)
FROM release_rows;
