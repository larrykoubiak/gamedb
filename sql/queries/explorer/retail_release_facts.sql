WITH verified AS (
    __VERIFIED_RELEASES_SQL__
), facts AS (
    SELECT verified.release_key, fact.fact_key,
        jsonb_agg(DISTINCT fact.fact_value ORDER BY fact.fact_value) AS items
    FROM verified
    JOIN catalog.software_fact fact ON fact.software_id = verified.software_id
    WHERE fact.is_selected AND fact.fact_key IN ('genre', 'player_count')
    GROUP BY verified.release_key, fact.fact_key
), checksums AS (
    SELECT verified.release_key, jsonb_agg(DISTINCT lower(file.crc_hex)) AS items
    FROM verified
    JOIN catalog.release_package member ON member.release_id = verified.release_id
    JOIN catalog.package package ON package.id = member.package_id
    JOIN catalog.package_file file ON file.package_id = package.id
    WHERE package.source_collection = 'No-Intro' AND package.resolved_path IS NOT NULL
        AND file.sha1_verified AND file.crc_verified AND file.crc_hex IS NOT NULL
    GROUP BY verified.release_key
)
SELECT coalesce(jsonb_object_agg(releases.release_key, jsonb_build_object(
    'genres', coalesce(genre.items, '[]'::jsonb),
    'players', coalesce(players.items, '[]'::jsonb),
    'crc32s', coalesce(checksums.items, '[]'::jsonb)
)), '{}'::jsonb)
FROM (SELECT DISTINCT release_key FROM verified) releases
LEFT JOIN facts genre ON genre.release_key = releases.release_key AND genre.fact_key = 'genre'
LEFT JOIN facts players ON players.release_key = releases.release_key AND players.fact_key = 'player_count'
LEFT JOIN checksums ON checksums.release_key = releases.release_key;
