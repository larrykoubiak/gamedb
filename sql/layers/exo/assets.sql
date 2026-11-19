WITH owners AS (
    SELECT record_no,entry_key AS owner_key FROM catalog.exo_entry
    UNION ALL
    SELECT record_no, 'collection:' || label FROM staging.exo_record
    WHERE snapshot_id=:snapshot AND record_type='Platform'
), links AS (
    SELECT o.owner_key,l.asset_no,l.role,l.label,l.basis
    FROM staging.exo_asset_link l JOIN owners o USING(record_no)
    JOIN staging.exo_asset a USING(snapshot_id,asset_no)
    WHERE l.snapshot_id=:snapshot AND (
        a.kind IN ('artwork','manual','music','video','url','collection_document') OR
        (a.kind IN ('extra','file') AND lower(a.logical_path) !~ '\.(bat|bsh|sh|msh|command|cmd|com|dll|ps1|msi|scr|vbs|lnk)$')
    )
)
SELECT owner_key,asset_no,role,label,array_agg(DISTINCT basis ORDER BY basis) AS evidence
INTO TEMPORARY _exo_links FROM links GROUP BY 1,2,3,4;

INSERT INTO catalog.related_asset(asset_key,asset_no,logical_path,kind,category,region)
SELECT encode(sha256(convert_to('exo/' || a.logical_path,'UTF8')),'hex'),a.asset_no,
       a.logical_path,a.kind,a.media_category,a.region
FROM staging.exo_asset a WHERE a.snapshot_id=:snapshot AND
    (a.asset_no IN (SELECT asset_no FROM _exo_links) OR a.kind='collection_document');

INSERT INTO catalog.related_location
SELECT a.asset_key,l.source_path,l.member_no,l.location_type,l.member_name,l.size_bytes,l.crc32,l.mtime_ns
FROM staging.exo_location l JOIN catalog.related_asset a USING(asset_no) WHERE l.snapshot_id=:snapshot;

INSERT INTO catalog.exo_asset_link
SELECT l.owner_key,a.asset_key,l.role,l.label,l.evidence FROM _exo_links l
JOIN catalog.related_asset a USING(asset_no);

INSERT INTO catalog.exo_asset_link
SELECT 'collection:eXo',asset_key,kind,logical_path,ARRAY['library document']
FROM catalog.related_asset a WHERE kind='collection_document'
AND NOT EXISTS (SELECT FROM catalog.exo_asset_link l WHERE l.asset_key=a.asset_key);
