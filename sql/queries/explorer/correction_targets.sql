WITH candidates AS (
    SELECT software.id AS software_id, software.display_name,
        software.identity_basis, count(membership.release_id) AS release_count,
        anchor.sha1_set_digest AS target_content_signature,
        anchor.source_title
    FROM catalog.software software
    JOIN catalog.software_release membership
      ON membership.software_id = software.id
    JOIN LATERAL (
        SELECT signature.sha1_set_digest, release.display_title AS source_title
        FROM catalog.software_release member
        JOIN catalog.release release ON release.id = member.release_id
        JOIN catalog.release_content_signature signature
          ON signature.release_id = release.id
        WHERE member.software_id = software.id
        ORDER BY CASE member.assignment_basis
            WHEN 'exact_sha1' THEN 1
            WHEN 'parent_clone' THEN 2
            WHEN 'manual_correction' THEN 3
            WHEN 'manual_override' THEN 4
            WHEN 'translation_original_title' THEN 5
            WHEN 'anchored_title' THEN 6
            ELSE 7 END,
            release.id
        LIMIT 1
    ) anchor ON true
    WHERE software.system_id = __SYSTEM_ID__
      AND software.id <> __EXCLUDE_SOFTWARE_ID__
      AND (
          __TITLE_FILTER__ = ''
          OR position(lower(__TITLE_FILTER__) in lower(software.display_name)) > 0
          OR EXISTS (
              SELECT 1
              FROM catalog.software_release searchable_membership
              JOIN catalog.release searchable_release
                ON searchable_release.id = searchable_membership.release_id
              WHERE searchable_membership.software_id = software.id
                AND position(lower(__TITLE_FILTER__)
                    in lower(searchable_release.display_title)) > 0
          )
      )
    GROUP BY software.id, software.display_name, software.identity_basis,
        anchor.sha1_set_digest, anchor.source_title
    ORDER BY lower(software.display_name), software.display_name, software.id
    LIMIT 50
)
SELECT coalesce(jsonb_agg(jsonb_build_object(
    'softwareId', software_id,
    'displayName', display_name,
    'identityBasis', identity_basis,
    'releaseCount', release_count,
    'targetContentSignature', target_content_signature,
    'sourceTitle', source_title
) ORDER BY lower(display_name), display_name, software_id), '[]'::jsonb)
FROM candidates;
