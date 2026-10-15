WITH chosen AS MATERIALIZED (
    SELECT
        title.id AS title_id,
        title.display_title AS title,
        preferred.release_id,
        preferred.score,
        preferred.breakdown,
        preferred.top_score_tie_count,
        preferred.tie_broken
    FROM catalog.title title
    JOIN catalog.user_preferred_release preferred
      ON preferred.title_id = title.id
    JOIN app.app_user user_account
      ON user_account.id = preferred.user_id
    WHERE title.system_id = __SYSTEM_ID__
      AND user_account.username = __USERNAME__
      AND (
          __TITLE_FILTER__ = ''
          OR position(lower(__TITLE_FILTER__) in lower(title.display_title)) > 0
          OR EXISTS (
              SELECT 1
              FROM catalog.title_alias alias
              JOIN catalog.title alias_title ON alias_title.id = alias.alias_title_id
              WHERE alias.preferred_title_id = title.id
                AND position(lower(__TITLE_FILTER__) in lower(alias_title.display_title)) > 0
          )
      )
),
page AS (
    SELECT *
    FROM chosen
    ORDER BY lower(title), title, title_id
    LIMIT __LIMIT__ OFFSET __OFFSET__
),
items AS (
    SELECT
        page.*,
        package.source_collection,
        package.archive_name,
        package.package_count,
        facts.languages,
        facts.regions,
        facts.revisions,
        facts.release_dates,
        facts.dump_modifications,
        facts.dump_statuses
    FROM page
    LEFT JOIN LATERAL (
        SELECT
            min(p.source_collection) AS source_collection,
            min(p.archive_name) AS archive_name,
            count(*) AS package_count
        FROM catalog.release_package rp
        JOIN catalog.package p ON p.id = rp.package_id
        WHERE rp.release_id = page.release_id
    ) package ON true
    LEFT JOIN LATERAL (
        SELECT
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'language'), '[]'::jsonb) AS languages,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'region'), '[]'::jsonb) AS regions,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'revision'), '[]'::jsonb) AS revisions,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'release_date'), '[]'::jsonb) AS release_dates,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'dump_modification'), '[]'::jsonb) AS dump_modifications,
            coalesce(jsonb_agg(f.fact_value ORDER BY f.fact_value)
                FILTER (WHERE f.fact_key = 'dump_status'), '[]'::jsonb) AS dump_statuses
        FROM catalog.release_fact f
        WHERE f.release_id = page.release_id
    ) facts ON true
)
SELECT jsonb_build_object(
    'total', (SELECT count(*) FROM chosen),
    'items', coalesce((
        SELECT jsonb_agg(
            jsonb_build_object(
                'titleId', items.title_id,
                'title', items.title,
                'score', items.score,
                'breakdown', items.breakdown,
                'topScoreTieCount', items.top_score_tie_count,
                'tieBroken', items.tie_broken,
                'sourceCollection', items.source_collection,
                'archiveName', items.archive_name,
                'packageCount', items.package_count,
                'languages', items.languages,
                'regions', items.regions,
                'revisions', items.revisions,
                'releaseDates', items.release_dates,
                'dumpModifications', items.dump_modifications,
                'dumpStatuses', items.dump_statuses
            ) ORDER BY lower(items.title), items.title, items.title_id
        )
        FROM items
    ), '[]'::jsonb)
);
