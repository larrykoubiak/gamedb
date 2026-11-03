SELECT jsonb_build_object(
    'catalogRevision', md5(
        user_account.username || '|' ||
        generation.generated_at::text || '|' ||
        generation.preference_signature || '|' ||
        metadata.signature || '|' || coalesce(media.signature, '')
    )
)
FROM app.user_score_generation generation
JOIN app.app_user user_account ON user_account.id = generation.user_id
JOIN LATERAL (
    SELECT md5(coalesce(string_agg(
        source_provider || ':' || source_revision || ':' || fact_count::text || ':' || genre_signature || ':' || source_score::text,
        '|' ORDER BY source_provider, source_revision
    ), '')) AS signature
    FROM (
        SELECT source_provider, source_revision, count(*) AS fact_count, max(source_score) AS source_score,
            md5(coalesce(string_agg(
                software_id::text || ':' || fact_value, '|' ORDER BY software_id, fact_value
            ) FILTER (WHERE fact_key='genre'), '')) AS genre_signature
        FROM catalog.software_fact
        GROUP BY source_provider, source_revision
    ) revisions
) metadata ON true
LEFT JOIN catalog.media_generation media ON media.singleton
WHERE user_account.username = __USERNAME__;
