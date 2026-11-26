WITH bundles AS MATERIALIZED (
    SELECT archive, published.manufacturer, published.system_name
    FROM (__CATALOGS_SQL__) published
    CROSS JOIN LATERAL jsonb_path_query(
        published.payload,
        '$.games[*].releases[*] ? (@.status == "matched").archives[*] ? (@.signature == $signature)',
        jsonb_build_object('signature', __RELEASE_SIGNATURE__::text)
    ) AS match(archive)
    WHERE jsonb_typeof(archive->'components') = 'array'
    LIMIT 1
),
components AS (
    SELECT part, ordinal
    FROM bundles
    CROSS JOIN LATERAL jsonb_array_elements(archive->'components') WITH ORDINALITY AS discs(part, ordinal)
),
verified AS MATERIALIZED (
    SELECT DISTINCT ON (ordinal) ordinal, package.id, package.archive_name, package.resolved_path,
           package.source_collection, signature.sha1_set_digest
    FROM components
    JOIN catalog.release_content_signature donor ON donor.sha1_set_digest = part->>'signature'
    JOIN catalog.release_package release_package ON release_package.release_id = donor.release_id
    JOIN catalog.software_release membership ON membership.release_id = donor.release_id
    JOIN catalog.software software ON software.id = membership.software_id
    JOIN catalog.system system ON system.id = software.system_id
    JOIN catalog.package package
      ON package.id = release_package.package_id AND package.archive_name = part->>'name'
    JOIN catalog.package_content_signature signature ON signature.package_id = package.id
    WHERE system.manufacturer_name = (SELECT manufacturer FROM bundles)
      AND system.system_name = (SELECT system_name FROM bundles)
      AND (package.source_collection = 'Redump'
          OR (package.source_collection = 'TOSEC-ISO' AND system.manufacturer_name = 'Commodore'
              AND system.system_name IN ('Amiga CD32', 'Amiga CDTV')))
      AND package.resolved_path IS NOT NULL
      AND EXISTS (SELECT FROM catalog.package_file file WHERE file.package_id = package.id)
      AND NOT EXISTS (
          SELECT FROM catalog.package_file file
          WHERE file.package_id = package.id AND (NOT file.sha1_verified OR file.sha1_hex IS NULL)
      )
    ORDER BY ordinal, package.id
),
packages AS (
    SELECT count(*) AS count, count(DISTINCT sha1_set_digest) AS distinct_count,
           jsonb_agg(jsonb_build_object(
               'packageSignature', sha1_set_digest,
               'archiveName', archive_name,
               'sourceCollection', source_collection,
               'resolvedPath', resolved_path,
               'mediaType', 'disc',
               'mediaSequence', ordinal,
               'mediaTotal', (SELECT count(*) FROM components),
               'files', files.items
           ) ORDER BY ordinal) AS items
    FROM verified
    CROSS JOIN LATERAL (
        SELECT jsonb_agg(jsonb_build_object(
            'memberPath', file.member_path, 'name', file.file_name, 'size', file.size, 'sha1', file.sha1_hex
        ) ORDER BY file.member_path, file.id) AS items
        FROM catalog.package_file file WHERE file.package_id = verified.id
    ) files
)
SELECT (
    SELECT jsonb_build_object(
        'releaseSignature', __RELEASE_SIGNATURE__::text,
        'title', archive->>'title',
        'system', jsonb_build_object('key', md5(manufacturer || E'\x1f' || system_name),
                                     'manufacturer', manufacturer, 'name', system_name),
        'packages', items
    )
    FROM bundles CROSS JOIN packages
    WHERE count = jsonb_array_length(archive->'components') AND count > 1 AND count = distinct_count
);
