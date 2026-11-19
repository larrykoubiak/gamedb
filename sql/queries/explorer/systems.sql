SELECT coalesce(jsonb_agg(
    jsonb_build_object(
        'id', systems.id,
        'key', systems.system_key,
        'manufacturer', systems.manufacturer_name,
        'name', systems.system_name,
        'category', systems.category,
        'gameCount', systems.game_count
    ) ORDER BY systems.manufacturer_name, systems.system_name
), '[]'::jsonb)
FROM (
    SELECT system.id,
        md5(system.manufacturer_name || E'\x1f' || system.system_name) AS system_key,
        system.manufacturer_name, system.system_name, system.category,
        count(preferred.release_id) AS game_count
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN __PREFERRED_VIEW__ preferred
      ON preferred.software_id = software.id
    JOIN app.app_user user_account
      ON user_account.id = preferred.user_id
    WHERE user_account.username = __USERNAME__
    GROUP BY system.id, system.manufacturer_name, system.system_name, system.category
) systems;
