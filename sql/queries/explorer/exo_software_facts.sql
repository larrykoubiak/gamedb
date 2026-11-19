SELECT jsonb_build_array(entry.facts, entry.source_list, publication.source_revision,
                         native.release_id IS NULL OR choice.score > native.score)
FROM app.exo_browse_choice choice
JOIN catalog.exo_entry entry USING (entry_key)
JOIN app.app_user account ON account.id = choice.user_id
LEFT JOIN __PREFERRED_VIEW__ native USING (user_id, software_id)
CROSS JOIN catalog.exo_publication publication
WHERE account.username = __USERNAME__ AND choice.software_id = __SOFTWARE_ID__
  AND choice.hide_mods = __HIDE_MODS__
ORDER BY choice.scope_id
LIMIT 1;
