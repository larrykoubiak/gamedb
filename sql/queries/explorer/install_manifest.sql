WITH inventory AS MATERIALIZED (
    SELECT release_id, sha1_set_digest, package_count
    FROM catalog.release_content_signature
    WHERE sha1_set_digest = __RELEASE_SIGNATURE__
),
legacy AS MATERIALIZED (
    SELECT
        release.id AS release_id,
        signature.sha1_set_digest AS release_signature,
        software.id AS software_id
    FROM inventory signature
    JOIN catalog.release release ON release.id = signature.release_id
    JOIN catalog.software_release membership ON membership.release_id = release.id
    JOIN catalog.software software ON software.id = membership.software_id
    JOIN (
        SELECT user_id, software_id, release_id, 0 AS priority FROM app.user_preferred_release
        UNION ALL
        SELECT user_id, software_id, release_id, 1 FROM app.user_rom_hack_fallback
        WHERE release_id IS NOT NULL
    ) preferred ON preferred.software_id = software.id AND preferred.release_id = release.id
    JOIN app.app_user user_account ON user_account.id = preferred.user_id
    WHERE user_account.username = __USERNAME__
    ORDER BY preferred.priority, software.id, release.id
    LIMIT 1
),
retail_links AS (
    SELECT NULL::bigint AS link_no, matched.archive
    FROM (__RETAIL_CATALOGS_SQL__) published
    CROSS JOIN LATERAL jsonb_path_query(
        published.payload,
        '$.games[*].releases[*] ? (@.status == "matched").archives[*] ? (@.signature == $signature)',
        jsonb_build_object('signature', __RELEASE_SIGNATURE__::text)
    ) AS matched(archive)
    WHERE EXISTS (SELECT FROM inventory) AND NOT EXISTS (SELECT FROM legacy)
),
selected AS MATERIALIZED (
    TABLE legacy
    UNION ALL
    (
        SELECT verified.release_id, verified.release_signature, verified.software_id
        FROM (__RETAIL_INSTALL_RELEASES_SQL__) verified
        ORDER BY verified.software_id, verified.release_id
        LIMIT 1
    )
),
packages AS (
    SELECT coalesce(jsonb_agg(
        jsonb_build_object(
            'packageSignature', package_signature.sha1_set_digest,
            'archiveName', package.archive_name,
            'sourceCollection', package.source_collection,
            'resolvedPath', package.resolved_path,
            'mediaType', release_package.media_type,
            'mediaPart', release_package.media_part,
            'mediaSequence', release_package.media_sequence,
            'mediaTotal', release_package.media_total,
            'mediaSide', release_package.media_side,
            'files', files.items
        ) ORDER BY release_package.media_sequence NULLS LAST,
            release_package.media_part NULLS LAST,
            release_package.media_side NULLS LAST,
            package.archive_name, package.id
    ), '[]'::jsonb) AS items
    FROM selected
    JOIN catalog.release_package release_package
      ON release_package.release_id = selected.release_id
    JOIN catalog.package package ON package.id = release_package.package_id
    JOIN catalog.package_content_signature package_signature
      ON package_signature.package_id = package.id
    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_agg(
            jsonb_build_object(
                'memberPath', file.member_path,
                'name', file.file_name,
                'size', file.size,
                'sha1', file.sha1_hex
            ) ORDER BY file.member_path, file.id
        ), '[]'::jsonb) AS items
        FROM catalog.package_file file
        WHERE file.package_id = package.id
    ) files ON true
)
SELECT (
    SELECT jsonb_build_object(
        'releaseSignature', selected.release_signature,
        'title', software.display_name,
        'system', jsonb_build_object(
            'key', md5(system.manufacturer_name || E'\x1f' || system.system_name),
            'manufacturer', system.manufacturer_name,
            'name', system.system_name
        ),
        'packages', packages.items
    )
    FROM selected
    JOIN catalog.software software ON software.id = selected.software_id
    JOIN catalog.system system ON system.id = software.system_id
    CROSS JOIN packages
);
