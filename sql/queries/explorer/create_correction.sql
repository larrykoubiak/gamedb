WITH selected_system AS (
    SELECT id, manufacturer_name, system_name
    FROM catalog.system WHERE id = __SYSTEM_ID__
), valid_subject AS (
    SELECT 1
    FROM selected_system system
    JOIN catalog.title title ON title.system_id = system.id
    JOIN catalog.release release ON release.title_id = title.id
    JOIN catalog.release_content_signature signature
      ON signature.release_id = release.id
    WHERE signature.sha1_set_digest = __SUBJECT_SIGNATURE__
    LIMIT 1
), valid_target AS (
    SELECT 1
    FROM selected_system system
    JOIN catalog.title title ON title.system_id = system.id
    JOIN catalog.release release ON release.title_id = title.id
    JOIN catalog.release_content_signature signature
      ON signature.release_id = release.id
    WHERE __ACTION__ = 'separate'
       OR signature.sha1_set_digest = __TARGET_SIGNATURE__
    LIMIT 1
), deactivated AS (
    UPDATE app.software_correction correction
    SET status = 'disabled'
    FROM selected_system system
    WHERE correction.manufacturer_name = system.manufacturer_name
      AND correction.system_name = system.system_name
      AND correction.subject_content_signature = __SUBJECT_SIGNATURE__
      AND correction.status = 'active'
      AND EXISTS (SELECT 1 FROM valid_subject)
      AND EXISTS (SELECT 1 FROM valid_target)
    RETURNING correction.id
), inserted AS (
    INSERT INTO app.software_correction (
        manufacturer_name, system_name, subject_content_signature,
        action, target_content_signature, note, created_by
    )
    SELECT system.manufacturer_name, system.system_name,
        __SUBJECT_SIGNATURE__, __ACTION__,
        CASE WHEN __ACTION__ = 'assign' THEN __TARGET_SIGNATURE__ END,
        __NOTE__, __USERNAME__
    FROM selected_system system
    WHERE EXISTS (SELECT 1 FROM valid_subject)
      AND EXISTS (SELECT 1 FROM valid_target)
    RETURNING id
)
SELECT jsonb_build_object(
    'created', EXISTS (SELECT 1 FROM inserted),
    'correctionId', (SELECT id FROM inserted)
);
