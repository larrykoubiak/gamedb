WITH hinted AS MATERIALIZED (
    SELECT software.id
    FROM catalog.software software
    JOIN catalog.system system ON system.id = software.system_id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    WHERE software.id = __SOFTWARE_ID__ AND __SOFTWARE_KEY_SQL__ = __KEY__
)
SELECT coalesce(
    (SELECT to_jsonb(id) FROM hinted),
    (SELECT to_jsonb(min(software.id))
     FROM catalog.software software
     JOIN catalog.system system ON system.id = software.system_id
     JOIN catalog.title title ON title.id = software.preferred_title_id
     WHERE __SOFTWARE_KEY_SQL__ = __KEY__
     HAVING count(*) = 1)
);
