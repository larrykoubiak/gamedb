WITH scored AS MATERIALIZED (
    SELECT
        score.release_id,
        score.score,
        score.rank_within_title,
        score.breakdown,
        (preferred.release_id = score.release_id) AS selected,
        release.display_title AS source_title
    FROM catalog.user_release_score score
    JOIN app.app_user user_account ON user_account.id = score.user_id
    JOIN catalog.release release ON release.id = score.release_id
    JOIN catalog.user_preferred_release preferred
      ON preferred.user_id = score.user_id
     AND preferred.title_id = score.title_id
    WHERE user_account.username = __USERNAME__
      AND score.title_id = __TITLE_ID__
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
                'sourceCollection', dat.romset,
                'archiveName', archive_name.archive_name,
                'contentSignature', signature.sha1_set_digest,
                'files', files.items
            ) ORDER BY release_package.media_sequence NULLS LAST,
                archive_name.archive_name, package.id
        ), '[]'::jsonb) AS items
        FROM catalog.release_package release_package
        JOIN derived.package package ON package.id = release_package.package_id
        JOIN derived.dat dat ON dat.id = package.dat_id
        JOIN derived.archive_name archive_name
          ON archive_name.id = package.archive_name_id
        LEFT JOIN catalog.package_content_signature signature
          ON signature.package_id = package.id
        LEFT JOIN LATERAL (
            SELECT coalesce(jsonb_agg(
                jsonb_build_object(
                    'name', file.file_name,
                    'size', file.size,
                    'sha1', file.sha1_hex,
                    'crc', file.crc_hex
                ) ORDER BY file.member_path, file.id
            ), '[]'::jsonb) AS items
            FROM derived.file file
            WHERE file.package_id = package.id
        ) files ON true
        WHERE release_package.release_id = scored.release_id
    ) packages ON true
)
SELECT coalesce(jsonb_agg(
    jsonb_build_object(
        'sourceTitle', release_rows.source_title,
        'score', release_rows.score,
        'rank', release_rows.rank_within_title,
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
    ) ORDER BY release_rows.rank_within_title,
        release_rows.score DESC, release_rows.release_id
), '[]'::jsonb)
FROM release_rows;
