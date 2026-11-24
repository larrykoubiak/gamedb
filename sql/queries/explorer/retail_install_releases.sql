WITH links AS (
    __LINKS_SQL__
)
SELECT DISTINCT links.link_no, signature.release_id, signature.sha1_set_digest AS release_signature,
    software.id AS software_id, packages.paths
FROM links
JOIN __SIGNATURE_SOURCE__ signature ON signature.sha1_set_digest = links.archive->>'signature'
JOIN catalog.software_release member ON member.release_id = signature.release_id
JOIN catalog.software software ON software.id = member.software_id
JOIN catalog.system system ON system.id = software.system_id
JOIN catalog.title title ON title.id = software.preferred_title_id
JOIN LATERAL (
    SELECT array_agg(package.archive_name ORDER BY package.archive_name) AS names,
        array_agg(package.resolved_path ORDER BY package.id) AS paths
    FROM catalog.release_package part
    JOIN catalog.package package ON package.id = part.package_id
    LEFT JOIN catalog.package_content_signature content
        ON content.package_id = package.id AND content.release_id = signature.release_id
    JOIN LATERAL (
        SELECT count(*) FILTER (WHERE lower(file.file_name) !~ '\.pok$') AS rom_count,
            md5(string_agg(file.sha1_hex, E'\n' ORDER BY file.sha1_hex)
                FILTER (WHERE lower(file.file_name) !~ '\.pok$')) AS sha1_set_digest,
            bool_and(file.sha1_verified AND file.sha1_hex IS NOT NULL) AS verified
        FROM catalog.package_file file
        WHERE file.package_id = package.id
    ) files ON true
    WHERE part.release_id = signature.release_id
    HAVING count(*) = signature.package_count
        AND bool_and(nullif(package.resolved_path, '') IS NOT NULL
                     AND content.sha1_set_digest IS NOT NULL AND files.verified IS TRUE
                     AND files.rom_count = content.rom_count
                     AND files.sha1_set_digest IS NOT DISTINCT FROM content.sha1_set_digest)
        AND md5(string_agg(content.sha1_set_digest, E'\n' ORDER BY content.sha1_set_digest)) = signature.sha1_set_digest
) packages ON packages.names = ARRAY(
    SELECT name
    FROM jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(links.archive->'archiveNames') = 'array'
            THEN links.archive->'archiveNames' ELSE '[]'::jsonb END
    ) AS published(name)
    ORDER BY name
)
WHERE __SOFTWARE_KEY_SQL__ = links.archive->>'softwareKey'
