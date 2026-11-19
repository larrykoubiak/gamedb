matching_software AS MATERIALIZED (
    SELECT software.id AS software_id
    FROM catalog.software software
    WHERE __TITLE_FILTER__ <> ''
      AND position(lower(__TITLE_FILTER__) in lower(software.display_name)) > 0
    UNION
    SELECT membership.software_id
    FROM catalog.title member_title
    JOIN catalog.release release ON release.title_id = member_title.id
    JOIN catalog.software_release membership ON membership.release_id = release.id
    WHERE __TITLE_FILTER__ <> ''
      AND position(lower(__TITLE_FILTER__) in lower(member_title.display_title)) > 0
), chosen AS MATERIALIZED (
    SELECT
        software.id AS software_id,
        software.preferred_title_id AS title_id,
        software.display_name AS title,
        software.identity_basis,
        system.id AS system_id,
        system.manufacturer_name,
        system.system_name,
        preferred.release_id,
        greatest(preferred.score,choice.score) AS score,
        CASE WHEN choice.score>preferred.score THEN choice.breakdown ELSE preferred.breakdown END AS breakdown,
        CASE WHEN choice.score>preferred.score THEN choice.tie_count
             WHEN choice.score=preferred.score THEN choice.tie_count+preferred.top_score_tie_count
             ELSE preferred.top_score_tie_count END AS top_score_tie_count,
        CASE WHEN choice.score>preferred.score THEN choice.tie_count>1
             WHEN choice.score=preferred.score THEN true ELSE preferred.tie_broken END AS tie_broken,
        CASE WHEN choice.edition_key IS NOT NULL THEN exo.work_key END AS work_key,
        choice.entry_key, exo.edition_count,
        CASE WHEN choice.edition_key IS NOT NULL THEN exo.media END AS exo_media,
        choice.is_mod AS source_mod, false AS source_only,
        coalesce(choice.score>preferred.score,false) AS exo_preferred, choice.edition_key, preferred.score AS install_score
    FROM catalog.software software
    LEFT JOIN catalog.exo_browse exo ON exo.scope_id=coalesce(__SYSTEM_ID__,0)
      AND exo.linked_software_id=software.id
    LEFT JOIN matching_software matched ON matched.software_id = software.id
    JOIN catalog.system system ON system.id = software.system_id
    JOIN __PREFERRED_VIEW__ preferred
      ON preferred.software_id = software.id AND preferred.release_id IS NOT NULL
    JOIN app.app_user user_account
      ON user_account.id = preferred.user_id
    LEFT JOIN app.exo_browse_choice choice ON choice.user_id=preferred.user_id AND choice.scope_id=exo.scope_id
      AND choice.software_id=software.id AND choice.hide_mods=__HIDE_MODS__
    LEFT JOIN catalog.exo_entry entry ON entry.entry_key=choice.entry_key
    WHERE (__SYSTEM_ID__ IS NULL OR software.system_id = __SYSTEM_ID__)
      AND user_account.username = __USERNAME__
      __METADATA_PREDICATES__
      AND (
          __TITLE_FILTER__ = ''
          OR matched.software_id IS NOT NULL
          OR (choice.edition_key IS NOT NULL AND EXISTS (
              SELECT FROM unnest(exo.search_names) n WHERE position(lower(__TITLE_FILTER__) in lower(n))>0))
      )
    UNION ALL
    SELECT exo.software_id,NULL::bigint,exo.work_title,'exo',exo.system_id,exo.manufacturer,exo.system_name,
           NULL::bigint,choice.score,choice.breakdown,choice.tie_count,choice.tie_count>1,
           exo.work_key,choice.entry_key,exo.edition_count,exo.media,choice.is_mod,true,true,choice.edition_key,NULL::bigint
    FROM catalog.exo_browse exo JOIN app.exo_browse_choice choice USING(scope_id,software_id)
    JOIN app.app_user u ON u.id=choice.user_id AND u.username=__USERNAME__
    JOIN catalog.exo_entry entry ON entry.entry_key=choice.entry_key
    WHERE exo.scope_id=coalesce(__SYSTEM_ID__,0) AND choice.hide_mods=__HIDE_MODS__
      AND (exo.linked_software_id IS NULL OR NOT EXISTS (
          SELECT FROM __PREFERRED_VIEW__ p JOIN app.app_user u ON u.id=p.user_id WHERE u.username=__USERNAME__
          AND p.software_id=exo.linked_software_id AND p.release_id IS NOT NULL))
      AND (__TITLE_FILTER__='' OR EXISTS (
          SELECT FROM unnest(exo.search_names) n WHERE position(lower(__TITLE_FILTER__) in lower(n))>0))
      __EXO_PREDICATES__
)
