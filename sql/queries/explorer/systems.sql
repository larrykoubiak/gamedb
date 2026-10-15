SELECT coalesce(jsonb_agg(
    jsonb_build_object(
        'id', systems.id,
        'manufacturer', systems.manufacturer_name,
        'name', systems.system_name,
        'gameCount', systems.game_count
    ) ORDER BY systems.manufacturer_name, systems.system_name
), '[]'::jsonb)
FROM (
    SELECT system.id, system.manufacturer_name, system.system_name,
        count(title.id) AS game_count
    FROM catalog.system system
    JOIN catalog.title title ON title.system_id = system.id
    JOIN catalog.user_preferred_release preferred
      ON preferred.title_id = title.id
    JOIN app.app_user user_account
      ON user_account.id = preferred.user_id
    WHERE user_account.username = __USERNAME__
    GROUP BY system.id, system.manufacturer_name, system.system_name
) systems;
