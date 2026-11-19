SELECT jsonb_build_object(
    'catalogRevision', md5(
        'rom-hack-filter-v1|' || user_account.username || '|' ||
        generation.generated_at::text || '|' ||
        generation.preference_signature || '|' ||
        listing.revision::text || '|' || coalesce(media.signature, '') || '|' || coalesce(exo.revision,'') || '|' || coalesce(exo_score.signature,'')
    )
)
FROM app.user_score_generation generation
JOIN app.app_user user_account ON user_account.id = generation.user_id
JOIN catalog.listing_generation listing ON listing.singleton
LEFT JOIN catalog.media_generation media ON media.singleton
LEFT JOIN app.exo_score_generation exo_score ON exo_score.user_id=user_account.id
LEFT JOIN catalog.exo_publication exo ON exo.singleton
WHERE user_account.username = __USERNAME__;
