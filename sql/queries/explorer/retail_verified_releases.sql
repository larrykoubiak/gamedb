WITH links AS (
    __LINKS_SQL__
)
SELECT DISTINCT links.release_key, software.id AS software_id, content.release_id
FROM links
JOIN catalog.software software ON software.id = links.software_id
JOIN catalog.system system ON system.id = software.system_id
JOIN catalog.title title ON title.id = software.preferred_title_id
JOIN catalog.software_release member ON member.software_id = software.id
JOIN catalog.release_content_signature content ON content.release_id = member.release_id
    AND content.sha1_set_digest = links.signature
WHERE __SOFTWARE_KEY_SQL__ = links.software_key
