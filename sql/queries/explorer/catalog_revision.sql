SELECT jsonb_build_object(
    'catalogRevision', md5(
        user_account.username || '|' ||
        generation.generated_at::text || '|' ||
        generation.preference_signature
    )
)
FROM app.user_score_generation generation
JOIN app.app_user user_account ON user_account.id = generation.user_id
WHERE user_account.username = __USERNAME__;
