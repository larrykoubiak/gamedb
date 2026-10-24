SELECT (
    SELECT jsonb_build_object(
        'schemaVersion', 2,
        'kind', 'arcade',
        'releaseSignature', a.install_signature,
        'signatureKind', 'machine_definition',
        'title', r.display_title,
        'emulator', jsonb_build_object('name',split_part(a.source_key,':',1),'version',a.version),
        'sourceKey', a.source_key,
        'system', jsonb_build_object('key',md5(s.manufacturer_name || E'\x1f' || s.system_name),'manufacturer',s.manufacturer_name,'name',s.system_name),
        'plan', a.plan
    )
    FROM catalog.arcade_release a JOIN catalog.release r ON r.id=a.release_id
    JOIN catalog.title t ON t.id=r.title_id JOIN catalog.system s ON s.id=t.system_id
    WHERE a.install_signature=__RELEASE_SIGNATURE__
);
