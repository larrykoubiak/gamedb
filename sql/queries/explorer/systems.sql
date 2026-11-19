WITH native AS (
    SELECT system.id, count(*) AS game_count
    FROM catalog.system system JOIN catalog.software software ON software.system_id=system.id
    JOIN __PREFERRED_VIEW__ preferred ON preferred.software_id=software.id
    JOIN app.app_user user_account ON user_account.id=preferred.user_id
    WHERE user_account.username = __USERNAME__ AND preferred.release_id IS NOT NULL GROUP BY system.id
), extra AS (
    SELECT b.scope_id,count(*) AS game_count FROM catalog.exo_browse b
    WHERE b.scope_id<>0 AND (__HIDE_MODS__ IS FALSE OR NOT b.all_mods)
    AND (b.linked_software_id IS NULL OR NOT EXISTS (
        SELECT FROM __PREFERRED_VIEW__ p JOIN app.app_user user_account ON user_account.id=p.user_id
        WHERE user_account.username = __USERNAME__ AND p.software_id=b.linked_software_id AND p.release_id IS NOT NULL))
    GROUP BY b.scope_id
), systems AS (
    SELECT s.id,md5(s.manufacturer_name || E'\x1f' || s.system_name) AS system_key,
        s.manufacturer_name,s.system_name,s.category,coalesce(n.game_count,0)+coalesce(e.game_count,0) AS game_count,
        'system' AS scope FROM catalog.system s LEFT JOIN native n USING(id) LEFT JOIN extra e ON e.scope_id=s.id
    UNION ALL SELECT s.id,s.shelf_key,'eXo',s.name,'computer',e.game_count,'collection'
    FROM catalog.exo_shelf s JOIN extra e ON e.scope_id=s.id
)
SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'key', systems.system_key,'manufacturer',manufacturer_name,
    'name',system_name,'category', systems.category,'gameCount',game_count,'scope',scope)
    ORDER BY manufacturer_name,system_name),'[]'::jsonb) FROM systems WHERE game_count>0;
