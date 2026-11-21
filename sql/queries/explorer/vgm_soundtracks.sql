WITH target AS (
    SELECT __SOFTWARE_KEY_SQL__ AS key
    FROM catalog.software software
    JOIN catalog.system system ON system.id = software.system_id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    WHERE software.id = __SOFTWARE_ID__
)
SELECT coalesce(jsonb_agg(jsonb_build_object(
    'title', soundtrack.title,
    'collection', soundtrack.collection,
    'assets', assets.items
) ORDER BY (soundtrack.collection = 'JoshW') DESC, (soundtrack.title LIKE '% [fixed]') DESC,
    soundtrack.collection, soundtrack.source_name, soundtrack.key), '[]')
FROM target JOIN vgm.soundtrack soundtrack ON soundtrack.target_key = target.key
    __ADDITIONAL_TARGETS_SQL__
CROSS JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'name', asset.detail->'name', 'format', asset.detail->'format',
        'kind', asset.detail->'kind', 'playable', asset.detail->'playable',
        'title', asset.detail->'title', 'artist', asset.detail->'artist',
        'subsongs', asset.detail->'subsongs',
        'url', '/related-media/vgm/' || asset.key
    ) ORDER BY asset.position) AS items
    FROM vgm.asset asset WHERE asset.soundtrack_key = soundtrack.key
) AS assets;
