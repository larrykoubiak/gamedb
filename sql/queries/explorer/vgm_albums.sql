SELECT coalesce(jsonb_agg(jsonb_build_object(
    'key', soundtrack.key,
    'title', soundtrack.title,
    'collection', soundtrack.collection,
    'sourceName', soundtrack.source_name,
    'assets', assets.items
) ORDER BY (soundtrack.collection = 'JoshW') DESC, (soundtrack.title LIKE '% [fixed]') DESC,
    soundtrack.collection, soundtrack.source_name, soundtrack.key), '[]') AS items
FROM vgm.soundtrack soundtrack
CROSS JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'name', asset.detail->'name', 'format', asset.detail->'format',
        'kind', asset.detail->'kind', 'playable', asset.detail->'playable',
        'title', asset.detail->'title', 'artist', asset.detail->'artist',
        'subsongs', asset.detail->'subsongs', 'defaultSubsong', asset.detail->'default_subsong',
        'subsongTitles', asset.detail->'subsong_titles',
        'url', '/related-media/vgm/' || asset.key
    ) ORDER BY asset.position) AS items
    FROM vgm.asset asset WHERE asset.soundtrack_key = soundtrack.key
) assets
WHERE __ALBUM_FILTER__
