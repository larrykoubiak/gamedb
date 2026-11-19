SELECT r.*, a.logical_path AS package, pkg.size_bytes AS package_size,pkg.mtime_ns AS package_mtime,
       cfg.logical_path AS config_path,cfg.size_bytes AS config_size,cfg.mtime_ns AS config_mtime,
       wrapper.source_path AS launcher_path,wrapper.size_bytes AS launcher_size,wrapper.mtime_ns AS launcher_mtime,
       coalesce(aliases.items,'[]'::jsonb) AS aliases
FROM staging.exo_record r JOIN staging.exo_asset_link l USING(snapshot_id,record_no)
JOIN staging.exo_asset a USING(snapshot_id,asset_no)
JOIN staging.exo_location pkg ON (pkg.snapshot_id,pkg.asset_no)=(a.snapshot_id,a.asset_no) AND pkg.location_type='file'
LEFT JOIN LATERAL (
    SELECT loc.source_path,loc.size_bytes,loc.mtime_ns FROM staging.exo_asset_link link
    JOIN staging.exo_location loc USING(snapshot_id,asset_no)
    WHERE (link.snapshot_id,link.record_no)=(r.snapshot_id,r.record_no) AND link.role='launcher'
    AND loc.location_type='file' LIMIT 1
) wrapper ON r.platform='Windows 9x'
LEFT JOIN LATERAL (
    SELECT a.logical_path,loc.size_bytes,loc.mtime_ns FROM staging.exo_asset_link cl
    JOIN staging.exo_asset a USING(snapshot_id,asset_no) JOIN staging.exo_location loc USING(snapshot_id,asset_no)
    WHERE (cl.snapshot_id,cl.record_no)=(r.snapshot_id,r.record_no) AND cl.role='configuration'
    AND loc.location_type='file' AND lower(a.logical_path) LIKE '%/dosbox.conf' LIMIT 1
) cfg ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(DISTINCT alt.fields ORDER BY alt.fields) AS items
    FROM staging.exo_record alt WHERE (alt.snapshot_id,alt.platform,alt.game_id)=(r.snapshot_id,r.platform,r.game_id)
    AND alt.record_type='AlternateName'
) aliases ON true
WHERE r.snapshot_id=:snapshot AND r.primary_game AND l.role='game_package' ORDER BY r.platform,r.game_id;
