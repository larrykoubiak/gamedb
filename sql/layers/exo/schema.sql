-- Browse-only source editions have stable keys independent of install content.
CREATE TABLE IF NOT EXISTS catalog.exo_publication (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    revision text NOT NULL, source_revision text NOT NULL, snapshot_id bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS catalog.exo_entry (
    entry_key text PRIMARY KEY, source_list text NOT NULL, game_id text NOT NULL,
    record_no integer NOT NULL UNIQUE, document_path text NOT NULL, title text NOT NULL,
    package_path text NOT NULL, fields jsonb NOT NULL, aliases jsonb NOT NULL,
    facts jsonb NOT NULL, tile_media jsonb NOT NULL DEFAULT '{}', UNIQUE (source_list, game_id)
);
CREATE TABLE IF NOT EXISTS catalog.exo_edition (
    edition_key text PRIMARY KEY, entry_key text NOT NULL REFERENCES catalog.exo_entry,
    work_key text NOT NULL, work_title text NOT NULL, selection text NOT NULL, label text NOT NULL,
    environment text NOT NULL, system_id bigint, platform_basis text NOT NULL,
    runner text, engine_game text, runner_version text, is_mod boolean NOT NULL,
    UNIQUE (entry_key, selection)
);
-- Acquire an exclusive lock only when upgrading an existing publication.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_attribute WHERE attrelid='catalog.exo_entry'::regclass
                   AND attname='tile_media' AND NOT attisdropped) THEN
        ALTER TABLE catalog.exo_entry ADD COLUMN tile_media jsonb NOT NULL DEFAULT '{}';
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS exo_edition_work_idx ON catalog.exo_edition(work_key);
CREATE INDEX IF NOT EXISTS exo_edition_entry_idx ON catalog.exo_edition(entry_key);
CREATE TABLE IF NOT EXISTS catalog.related_asset (
    asset_key text PRIMARY KEY, asset_no integer NOT NULL UNIQUE, logical_path text UNIQUE NOT NULL,
    kind text NOT NULL, category text, region text, content_sha256 text
);
CREATE TABLE IF NOT EXISTS catalog.related_location (
    asset_key text NOT NULL REFERENCES catalog.related_asset, source_path text NOT NULL,
    member_no integer NOT NULL, location_type text NOT NULL, member_name text,
    size_bytes bigint, crc32 text, mtime_ns bigint, PRIMARY KEY (source_path, member_no)
);
CREATE INDEX IF NOT EXISTS related_location_asset_idx ON catalog.related_location(asset_key);
CREATE TABLE IF NOT EXISTS catalog.exo_asset_link (
    owner_key text NOT NULL, asset_key text NOT NULL REFERENCES catalog.related_asset,
    role text NOT NULL, label text NOT NULL, evidence text[] NOT NULL,
    PRIMARY KEY (owner_key, asset_key, role, label)
);
CREATE TABLE IF NOT EXISTS catalog.exo_shelf (
    id bigint PRIMARY KEY, shelf_key text UNIQUE NOT NULL, name text UNIQUE NOT NULL
);
CREATE INDEX IF NOT EXISTS exo_asset_link_asset_idx ON catalog.exo_asset_link(asset_key);
-- A row per work in each applicable hardware system, collection, and global search.
-- Existing DAT software IDs are reused only when the edition identity is corroborated.
CREATE TABLE IF NOT EXISTS catalog.exo_browse (
    scope_id bigint NOT NULL, software_id bigint NOT NULL, work_key text NOT NULL,
    entry_key text NOT NULL REFERENCES catalog.exo_entry, work_title text NOT NULL,
    system_id bigint, system_name text NOT NULL, manufacturer text NOT NULL,
    linked_software_id bigint, match_basis text, edition_count integer NOT NULL,
    all_mods boolean NOT NULL, search_names text[] NOT NULL, media jsonb NOT NULL,
    PRIMARY KEY(scope_id,software_id)
);
CREATE INDEX IF NOT EXISTS exo_browse_software_idx ON catalog.exo_browse(software_id);
CREATE INDEX IF NOT EXISTS exo_browse_entry_idx ON catalog.exo_browse(entry_key);
CREATE INDEX IF NOT EXISTS exo_browse_linked_idx ON catalog.exo_browse(scope_id,linked_software_id)
    WHERE linked_software_id IS NOT NULL;
