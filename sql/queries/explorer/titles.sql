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
        __SOFTWARE_KEY_SQL__ AS software_key,
        CASE WHEN page.exo_preferred THEN CASE entry.source_list
            WHEN 'MS-DOS' THEN 'eXoDOS' WHEN 'Windows 9x' THEN 'eXoWin9x'
            WHEN 'ScummVM' THEN 'eXoScummVM' WHEN 'ScummVM SVN' THEN 'eXoScummVM SVN' END ELSE package.source_collection END AS source_collection,
        entry.source_list, package.source_collection AS install_source, install_release.display_title AS install_title,
        CASE WHEN page.exo_preferred THEN regexp_replace(entry.package_path,'^.*/','') ELSE package.archive_name END AS archive_name,
        CASE WHEN page.exo_preferred THEN 1 ELSE package.package_count END AS package_count,
        CASE WHEN page.exo_preferred THEN coalesce(entry.facts->'language','[]'::jsonb) ELSE facts.languages END AS languages,
        CASE WHEN page.exo_preferred THEN coalesce(entry.facts->'region','[]'::jsonb) ELSE facts.regions END AS regions,
        CASE WHEN page.exo_preferred THEN '[]'::jsonb ELSE facts.revisions END AS revisions,
        CASE WHEN page.exo_preferred THEN CASE WHEN entry.fields ? 'ReleaseDate'
             THEN jsonb_build_array(left(entry.fields->>'ReleaseDate',10)) ELSE '[]'::jsonb END
             ELSE facts.release_dates END AS release_dates,
        CASE WHEN page.exo_preferred THEN CASE WHEN page.source_mod THEN '["hacked"]'::jsonb ELSE '[]'::jsonb END
             ELSE facts.dump_modifications END AS dump_modifications,
        CASE WHEN page.exo_preferred THEN page.source_mod ELSE facts.is_rom_hack END AS is_rom_hack,
        CASE WHEN page.exo_preferred THEN '[]'::jsonb ELSE facts.dump_statuses END AS dump_statuses,
        CASE WHEN page.exo_preferred THEN media.items || coalesce(page.exo_media,'{}'::jsonb) || entry.tile_media
             ELSE coalesce(page.exo_media,'{}'::jsonb) || coalesce(entry.tile_media,'{}'::jsonb) || media.items END AS media,
        CASE WHEN entry.entry_key IS NOT NULL THEN jsonb_strip_nulls(jsonb_build_object(
            'genre',entry.facts->'genre','developer',entry.facts->'developer','publisher',entry.facts->'publisher',
            'franchise',entry.facts->'franchise','player_count',entry.facts->'player_count')) END AS browse_facts,
        CASE WHEN arcade.release_id IS NOT NULL THEN jsonb_build_object('complete',(arcade.plan->>'complete')::boolean,'emulationStatus',arcade.plan->>'emulationStatus','preferredCore',arcade.plan->>'preferredCore','compatibleEmulators',arcade.plan->'compatibleEmulators','issues',(SELECT jsonb_agg(DISTINCT issue->>'reason') FROM jsonb_array_elements(arcade.plan->'missing') issue)) END AS arcade,
        coalesce(arcade.install_signature, signature.sha1_set_digest) AS preferred_release_signature
    FROM page
    LEFT JOIN catalog.software software ON NOT page.source_only AND software.id = page.software_id
    LEFT JOIN catalog.system system ON system.id = software.system_id
    LEFT JOIN catalog.title title ON title.id = software.preferred_title_id
    LEFT JOIN catalog.release install_release ON install_release.id=page.release_id
    LEFT JOIN catalog.exo_entry entry ON entry.entry_key=page.entry_key
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
            catalog.is_rom_hack(array_agg(f.fact_value)
                FILTER (WHERE f.fact_key = 'dump_modification')) AS is_rom_hack,
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
)
SELECT jsonb_build_object(
    'total', (SELECT count(*) FROM chosen),
    'items', coalesce((
        SELECT jsonb_agg(
            jsonb_build_object(
                'softwareId', items.software_id,
                'softwareKey', CASE WHEN NOT items.source_only THEN items.software_key END,
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
                'isRomHack', items.is_rom_hack,
                'dumpStatuses', items.dump_statuses,
                'media', items.media
            ) || CASE WHEN items.work_key IS NULL THEN '{}'::jsonb ELSE jsonb_build_object(
                'sourceDetailKey', items.work_key,
                'preferredEditionKey', CASE WHEN items.exo_preferred THEN items.edition_key END,
                'installSourceCollection', CASE WHEN items.preferred_release_signature IS NOT NULL THEN items.install_source END,
                'installReleaseTitle', CASE WHEN items.preferred_release_signature IS NOT NULL THEN items.install_title END,
                'installScore', CASE WHEN items.preferred_release_signature IS NOT NULL THEN items.install_score END,
                'sourceEntryKey', items.entry_key,
                'sourceList',items.source_list,
                'sourceRevision',CASE WHEN items.entry_key IS NOT NULL THEN
                    (SELECT source_revision FROM catalog.exo_publication WHERE singleton) END,
                'sourceOnly', items.source_only,
                'sourceFacts', items.browse_facts,
                'editionCount', items.edition_count
            ) END ORDER BY lower(items.title), items.title, items.software_id
        )
        FROM items
    ), '[]'::jsonb)
);
