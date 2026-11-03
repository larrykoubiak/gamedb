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
        preferred.score,
        preferred.breakdown,
        preferred.top_score_tie_count,
        preferred.tie_broken
    FROM catalog.software software
    LEFT JOIN matching_software matched ON matched.software_id = software.id
    JOIN catalog.system system ON system.id = software.system_id
    JOIN app.user_preferred_release preferred
      ON preferred.software_id = software.id
    JOIN app.app_user user_account
      ON user_account.id = preferred.user_id
    WHERE (__SYSTEM_ID__ IS NULL OR software.system_id = __SYSTEM_ID__)
      AND user_account.username = __USERNAME__
      __METADATA_PREDICATES__
      AND (
          __TITLE_FILTER__ = ''
          OR matched.software_id IS NOT NULL
      )
)
