WITH __SOFTWARE_SCOPE__,
page AS (
    SELECT *
    FROM chosen
    ORDER BY lower(title), title, software_id
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
        facts.dump_statuses,
        media.items AS media,
        CASE WHEN arcade.release_id IS NOT NULL THEN jsonb_build_object('complete',(arcade.plan->>'complete')::boolean,'emulationStatus',arcade.plan->>'emulationStatus','preferredCore',arcade.plan->>'preferredCore','compatibleEmulators',arcade.plan->'compatibleEmulators','issues',(SELECT jsonb_agg(DISTINCT issue->>'reason') FROM jsonb_array_elements(arcade.plan->'missing') issue)) END AS arcade,
        coalesce(arcade.install_signature, signature.sha1_set_digest) AS preferred_release_signature
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
    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_object_agg(
            selected.media_kind,
            jsonb_build_object(
                'path', asset.relative_path,
                'provider', asset.provider,
                'matchBasis', selected.match_basis,
                'regionMatch', selected.region_match
            ) ORDER BY selected.media_kind
        ), '{}'::jsonb) AS items
        FROM catalog.software_media selected
        JOIN catalog.media asset ON asset.id = selected.media_id
        WHERE selected.software_id = page.software_id
    ) media ON true
    LEFT JOIN catalog.arcade_release arcade ON arcade.release_id = page.release_id
    LEFT JOIN catalog.release_content_signature signature
      ON signature.release_id = page.release_id
    WHERE signature.release_id IS NOT NULL OR arcade.release_id IS NOT NULL
)
SELECT jsonb_build_object(
    'total', (SELECT count(*) FROM chosen),
    'items', coalesce((
        SELECT jsonb_agg(
            jsonb_build_object(
                'softwareId', items.software_id,
                'systemId', items.system_id,
                'manufacturer', items.manufacturer_name,
                'systemName', items.system_name,
                'preferredReleaseSignature', items.preferred_release_signature,
                'titleId', items.title_id,
                'title', items.title,
                'identityBasis', items.identity_basis,
                'score', items.score,
                'arcade', items.arcade,
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
                'dumpStatuses', items.dump_statuses,
                'media', items.media
            ) ORDER BY lower(items.title), items.title, items.software_id
        )
        FROM items
    ), '[]'::jsonb)
);
