SELECT asset.detail
FROM vgm.asset asset JOIN vgm.soundtrack soundtrack ON soundtrack.key = asset.soundtrack_key
WHERE asset.key = __ASSET_KEY__ AND soundtrack.target_key IS NOT NULL;
