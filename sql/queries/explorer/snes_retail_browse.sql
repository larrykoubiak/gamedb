WITH snapshot AS (
    SELECT payload FROM app.snes_retail_catalog WHERE singleton LIMIT 1
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
        'status', release->'status', 'boxart', release->'artwork'->'boxart',
        'archiveTitles', jsonb_path_query_array(release, '$.archives[*].title'),
        'archiveSignatures', jsonb_path_query_array(release, '$.archives[*].signature')
    ) ORDER BY release_order) AS items
    FROM releases
    GROUP BY game_order
)
SELECT jsonb_build_object('source', payload->'source', 'summary', payload->'summary', 'games', (
    SELECT jsonb_agg(jsonb_build_object(
        'key', game->'key', 'title', game->'title', 'aliases', game->'aliases',
        'genres', coalesce(game_genres.items, '[]'::jsonb), 'releases', game_releases.items
    ) ORDER BY games.game_order)
    FROM games
    LEFT JOIN game_genres USING (game_order)
    LEFT JOIN game_releases USING (game_order)
))
FROM snapshot;
