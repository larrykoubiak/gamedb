-- Keep the library and its review results across catalog rebuilds.
CREATE SCHEMA IF NOT EXISTS vgm;
CREATE TABLE IF NOT EXISTS vgm.soundtrack (
    key text PRIMARY KEY,
    collection text NOT NULL,
    source_name text NOT NULL,
    title text NOT NULL,
    platform text[],
    aliases text[] NOT NULL,
    status text NOT NULL,
    target_key text,
    candidates jsonb NOT NULL,
    match_evidence jsonb NOT NULL DEFAULT '{}',
    issues text[] NOT NULL,
    CHECK ((status = 'matched') = (target_key IS NOT NULL))
);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_attribute
        WHERE attrelid = 'vgm.soundtrack'::regclass
          AND attname = 'match_evidence' AND NOT attisdropped
    ) THEN
        ALTER TABLE vgm.soundtrack ADD COLUMN match_evidence jsonb NOT NULL DEFAULT '{}';
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS vgm_soundtrack_target_idx ON vgm.soundtrack (target_key)
    WHERE target_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS vgm.asset (
    key text PRIMARY KEY,
    soundtrack_key text NOT NULL REFERENCES vgm.soundtrack(key) ON DELETE CASCADE,
    position integer NOT NULL,
    detail jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS vgm_asset_soundtrack_idx ON vgm.asset (soundtrack_key, position);
