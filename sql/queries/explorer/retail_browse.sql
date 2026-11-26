WITH snapshot AS (
    SELECT payload FROM __CATALOG_TABLE__ WHERE singleton LIMIT 1
), games AS (
    SELECT game, game_order
    FROM snapshot
    CROSS JOIN LATERAL jsonb_array_elements(payload->'games') WITH ORDINALITY AS g(game, game_order)
), releases AS (
    SELECT game_order, release, release_order
    FROM games
    CROSS JOIN LATERAL jsonb_array_elements(game->'releases') WITH ORDINALITY AS r(release, release_order)
), game_genres AS (
    __GENRES_SQL__
), game_releases AS (
    SELECT game_order, jsonb_agg(jsonb_build_object(
        'key', release->'key', 'market', release->'market', 'titles', release->'titles',
        'hardware', release->'hardware', 'compatibleHardware', release->'compatibleHardware',
        'requiredHardware', release->'requiredHardware',
        'status', release->'status', 'boxart', release->'artwork'->'boxart', 'productCodes', release->'productCodes',
        'hasTranslations', (release ? 'translations'),
        'cover', CASE WHEN release ? 'setNames' OR NOT (release->'artwork' ? 'boxart') THEN
            coalesce(release->'artwork'->'boxart', release->'artwork'->'flyer',
                release->'artwork'->'marquee', release->'artwork'->'cartridge',
                release->'artwork'->'title', release->'artwork'->'snap') END,
        'archiveTitles', coalesce(release->'setNames', jsonb_path_query_array(release, '$.archives[*].title')),
        'archiveSignatures', jsonb_path_query_array(release, '$.archives[*].signature')
            || jsonb_path_query_array(release, '$.arcadeSets[*] ? (@.complete == true).installSignature')
    ) ORDER BY release_order) AS items
    FROM releases
    GROUP BY game_order
)
SELECT jsonb_build_object('source', payload->'source', 'addonSources', payload->'addonSources',
    'summary', payload->'summary', 'games', (
    SELECT jsonb_agg(jsonb_build_object(
        'key', game->'key', 'title', game->'title', 'aliases', game->'aliases',
        'genres', coalesce(game_genres.items, game->'genres', '[]'::jsonb), 'releases', game_releases.items
    ) ORDER BY games.game_order)
    FROM games
    LEFT JOIN game_genres USING (game_order)
    LEFT JOIN game_releases USING (game_order)
))
FROM snapshot;
