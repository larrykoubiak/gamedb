WITH target AS (
    SELECT software.id, __SOFTWARE_KEY_SQL__ AS key,
           ARRAY[system.manufacturer_name, system.system_name] AS platform
    FROM catalog.software software
    JOIN catalog.system system ON system.id = software.system_id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    WHERE software.id = __SOFTWARE_ID__
)
SELECT jsonb_build_object(
    'platform', target.platform,
    'releaseVersions', coalesce((
        SELECT jsonb_agg(jsonb_build_array(fact.fact_key, fact.fact_value))
        FROM __PREFERRED_VIEW__ preferred
        JOIN app.app_user account ON account.id = preferred.user_id
        JOIN catalog.release_fact fact ON fact.release_id = preferred.release_id
        WHERE preferred.software_id = target.id AND account.username = __USERNAME__
          AND fact.fact_key IN ('version', 'revision')
    ), '[]'),
    'albums', albums.items
)
FROM target
CROSS JOIN LATERAL (
    __ALBUMS_SQL__
) albums;
