SELECT jsonb_build_object('kind',a.kind,'path',a.logical_path,'revision',p.source_revision,'locations',
    (SELECT jsonb_agg(jsonb_build_object('source_path',l.source_path,'member_no',l.member_no,
        'location_type',l.location_type,'member_name',l.member_name,'size_bytes',l.size_bytes,'crc32',l.crc32,
        'mtime_ns',l.mtime_ns) ORDER BY l.member_no,l.source_path)
    FROM catalog.related_location l WHERE l.asset_key=a.asset_key))
FROM catalog.related_asset a CROSS JOIN catalog.exo_publication p WHERE a.asset_key=__ASSET_KEY__;
