WITH requested AS (
    SELECT coalesce(
        (SELECT work_key FROM catalog.exo_edition WHERE work_key=__WORK_KEY__ LIMIT 1),
        (SELECT work_key FROM catalog.exo_work_alias WHERE alias_key=__WORK_KEY__),
        (SELECT min(work_key) FROM catalog.exo_edition WHERE entry_key=__WORK_KEY__
         HAVING count(DISTINCT work_key)=1)
    ) AS work_key
), editions AS MATERIALIZED (
    SELECT e.*, s.system_name,s.manufacturer_name,score.score,score.breakdown FROM catalog.exo_edition e
    LEFT JOIN catalog.system s ON s.id=e.system_id
    LEFT JOIN app.exo_edition_score score ON score.edition_key=e.edition_key AND
        score.user_id=(SELECT id FROM app.app_user WHERE username=__USERNAME__)
    WHERE e.work_key=(SELECT work_key FROM requested)
), entries AS MATERIALIZED (
    SELECT g.* FROM catalog.exo_entry g WHERE g.entry_key IN (SELECT entry_key FROM editions)
), owners AS (
    SELECT entry_key AS owner_key,source_list,title FROM entries
    UNION SELECT 'collection:'||source_list,source_list,source_list FROM entries
    UNION SELECT 'collection:ScummVM','ScummVM','ScummVM' FROM entries WHERE source_list='ScummVM SVN'
    UNION SELECT 'collection:eXo','eXo','eXo'
), assets AS (
    SELECT a.asset_key,a.kind,a.category,a.region,a.logical_path,a.content_sha256,
           l.role,l.label,l.evidence,o.owner_key,o.source_list,o.title
    FROM owners o JOIN catalog.exo_asset_link l USING(owner_key) JOIN catalog.related_asset a USING(asset_key)
), attached AS (
    SELECT coalesce(content_sha256,asset_key) AS identity,kind,min(asset_key) AS asset_key,
           min(category) AS category,min(region) AS region,min(role) AS role,
           min(regexp_replace(logical_path,'^.*/','')) AS name,
           jsonb_agg(DISTINCT jsonb_build_object('ownerKey',owner_key,'sourceList',source_list,'title',title,
                         'assetKey',asset_key,'label',label,'role',role,'basis',evidence)) AS sources
    FROM assets GROUP BY 1,2
)
SELECT jsonb_build_object(
    'key',(SELECT work_key FROM requested),
    'entries',(SELECT jsonb_agg(jsonb_build_object('key',entry_key,'title',title,'sourceList',source_list,
        'gameId',game_id,'document',document_path,'package',package_path,'facts',facts,'fields',fields,
        'alternateNames',aliases) ORDER BY source_list,entry_key) FROM entries),
    'editions',(SELECT jsonb_agg(jsonb_build_object('key',edition_key,'entryKey',entry_key,'title',work_title,
        'label',label,'selection',selection,'environment',environment,'system',system_name,
        'manufacturer',manufacturer_name,'platformEvidence',platform_basis,'runner',runner,
        'score',score,'breakdown',breakdown,'engineGame',engine_game,'runnerVersion',runner_version,'isRomHack',is_mod,'installable',false)
        ORDER BY environment,label,edition_key) FROM editions),
    'assets',coalesce((SELECT jsonb_agg(jsonb_build_object('key',asset_key,'kind',kind,'category',category,
        'region',region,'role',role,'label',name,'url','/related-media/'||asset_key,'sources',sources)
        ORDER BY kind,name,asset_key) FROM attached),'[]'::jsonb)
) WHERE EXISTS (SELECT FROM entries);
