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
        count(software.id) AS game_count
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN app.user_preferred_release preferred
      ON preferred.software_id = software.id
    JOIN app.app_user user_account
      ON user_account.id = preferred.user_id
    WHERE user_account.username = __USERNAME__
    GROUP BY system.id, system.manufacturer_name, system.system_name
) systems;
