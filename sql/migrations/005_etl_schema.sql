-- Separate imported/derived data from the manually maintained reference layer.
-- Requires 004. Table moves preserve OIDs, IDs, data, sequences and foreign keys.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '5s';

SELECT to_regclass('etl.schema_migration') IS NOT NULL AS has_etl_ledger \gset
\if :has_etl_ledger
    SELECT EXISTS (
        SELECT 1 FROM etl.schema_migration WHERE version = '005_etl_schema'
    ) AS already_applied \gset
\else
    \set already_applied false
\endif

\if :already_applied
    \echo '005_etl_schema is already applied.'
    ROLLBACK;
\else

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ref.schema_migration WHERE version = '004_system_archive'
    ) THEN
        RAISE EXCEPTION 'Apply 004_system_archive before 005_etl_schema';
    END IF;
END;
$$;

SELECT pg_advisory_xact_lock(hashtext('gamedb:source_sync'));
SELECT pg_advisory_xact_lock(hashtext('gamedb:archive_name_parse'));

CREATE SCHEMA IF NOT EXISTS etl;
COMMENT ON SCHEMA etl IS
    'RomVault source identities, generated mapping results, parsing and refresh functions. IDs and reviewed decisions are persistent.';
COMMENT ON SCHEMA ref IS
    'Reserved for manually maintained reference data, normally loaded from versioned static files.';

ALTER TABLE ref.dat SET SCHEMA etl;
ALTER TABLE ref.archive_name SET SCHEMA etl;
ALTER TABLE ref.system_mapping SET SCHEMA etl;
ALTER TABLE ref.schema_migration SET SCHEMA etl;

ALTER VIEW ref.v_romset SET SCHEMA etl;
ALTER VIEW ref.v_romset_system SET SCHEMA etl;
ALTER VIEW ref.v_system_mapping_review SET SCHEMA etl;
ALTER VIEW ref.v_archive SET SCHEMA etl;
ALTER VIEW ref.v_archive_tag SET SCHEMA etl;
ALTER VIEW ref.v_archive_name_review SET SCHEMA etl;

ALTER FUNCTION ref.system_name_key(text) SET SCHEMA etl;
ALTER FUNCTION ref.refresh_system_mapping() SET SCHEMA etl;
ALTER FUNCTION ref.refresh_archives() SET SCHEMA etl;

-- PostgreSQL updates stored view/FK dependencies when their objects move.
-- PL/pgSQL bodies contain SQL text, so their qualified references must be replaced.

CREATE OR REPLACE FUNCTION etl.refresh_system_mapping()
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE affected_rows bigint;
BEGIN
    WITH source_pairs AS MATERIALIZED (
        SELECT DISTINCT manufacturer, system FROM etl.v_romset
        WHERE btrim(manufacturer) <> '' AND btrim(system) <> ''
    ), canonical_keys AS MATERIALIZED (
        SELECT id, etl.system_name_key(manufacturer_name) AS manufacturer_key,
            etl.system_name_key(name) AS system_key
        FROM public.system
    ), candidates AS (
        SELECT p.manufacturer, p.system, e.id AS exact_id,
            count(n.id) AS candidate_count, min(n.id) AS normalized_id
        FROM source_pairs p
        LEFT JOIN public.system e ON e.manufacturer_name = p.manufacturer AND e.name = p.system
        LEFT JOIN canonical_keys n ON n.manufacturer_key = etl.system_name_key(p.manufacturer)
                                 AND n.system_key = etl.system_name_key(p.system)
        GROUP BY p.manufacturer, p.system, e.id
    )
    INSERT INTO etl.system_mapping AS existing (manufacturer, system, system_id, match_method, notes)
    SELECT manufacturer, system,
        CASE WHEN exact_id IS NOT NULL THEN exact_id WHEN candidate_count = 1 THEN normalized_id END,
        CASE WHEN exact_id IS NOT NULL THEN 'exact'
             WHEN candidate_count = 1 THEN 'normalized'
             WHEN candidate_count > 1 THEN 'ambiguous' ELSE 'unmatched' END,
        CASE WHEN exact_id IS NOT NULL THEN NULL
             WHEN candidate_count = 1 THEN 'Case, whitespace or separator variation.'
             WHEN candidate_count > 1 THEN 'Multiple canonical pairs share this normalized name; review required.'
             ELSE 'No canonical name match; add an explicit alias or canonical system.' END
    FROM candidates
    ON CONFLICT (manufacturer, system) DO UPDATE
    SET system_id = EXCLUDED.system_id, match_method = EXCLUDED.match_method, notes = EXCLUDED.notes
    WHERE existing.match_method = 'unmatched' AND EXCLUDED.match_method IN ('exact', 'normalized');
    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows;
END;
$$;

CREATE OR REPLACE FUNCTION etl.refresh_archives()
RETURNS TABLE(dats_changed bigint, names_added bigint, archives_changed bigint, archives_absent bigint)
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('gamedb:source_sync'));
    CREATE TEMP TABLE _gamedb_dats ON COMMIT DROP AS
        SELECT * FROM etl.v_romset_system;
    ANALYZE _gamedb_dats;

    INSERT INTO etl.dat AS existing (dat_path, dat_name, romset, manufacturer, system, additional, system_id)
    SELECT key, name, romset, manufacturer, system, additional, system_id FROM _gamedb_dats
    ON CONFLICT (dat_path, dat_name) DO UPDATE
    SET romset = EXCLUDED.romset, manufacturer = EXCLUDED.manufacturer,
        system = EXCLUDED.system, additional = EXCLUDED.additional, system_id = EXCLUDED.system_id
    WHERE (existing.romset, existing.manufacturer, existing.system, existing.additional, existing.system_id)
        IS DISTINCT FROM
          (EXCLUDED.romset, EXCLUDED.manufacturer, EXCLUDED.system, EXCLUDED.additional, EXCLUDED.system_id);
    GET DIAGNOSTICS dats_changed = ROW_COUNT;

    CREATE TEMP TABLE _gamedb_archive_names ON COMMIT DROP AS
    SELECT d.id AS dat_id, d.romset, d.system_id, rf.game_display_name AS archive_name,
        count(*) AS staged_row_count
    FROM staging.rv_files rf
    JOIN _gamedb_dats live ON live.key = rf.dat_root_full_name AND live.name = rf.dat_name
    JOIN etl.dat d ON d.dat_path = live.key AND d.dat_name = live.name
    WHERE nullif(btrim(rf.game_display_name), '') IS NOT NULL
    GROUP BY d.id, d.romset, d.system_id, rf.game_display_name;
    ANALYZE _gamedb_archive_names;

    INSERT INTO etl.archive_name (romset, archive_name, parsed_at)
    SELECT DISTINCT a.romset, a.archive_name, NULL::timestamptz
    FROM _gamedb_archive_names a
    WHERE NOT EXISTS (SELECT 1 FROM etl.archive_name p WHERE p.romset = a.romset AND p.archive_name = a.archive_name)
    ON CONFLICT (romset, archive_name) DO NOTHING;
    GET DIAGNOSTICS names_added = ROW_COUNT;

    CREATE TEMP TABLE _gamedb_archives ON COMMIT DROP AS
    SELECT a.dat_id, p.id AS archive_name_id, a.system_id, a.staged_row_count
    FROM _gamedb_archive_names a
    JOIN etl.archive_name p ON p.romset = a.romset AND p.archive_name = a.archive_name;
    CREATE UNIQUE INDEX ON _gamedb_archives(dat_id, archive_name_id);
    ANALYZE _gamedb_archives;
    DROP TABLE _gamedb_archive_names;

    INSERT INTO public.archive AS existing (dat_id, archive_name_id, system_id, staged_row_count)
    SELECT dat_id, archive_name_id, system_id, staged_row_count FROM _gamedb_archives
    ON CONFLICT (dat_id, archive_name_id) DO UPDATE
    SET system_id = CASE WHEN existing.system_assignment = 'manual' THEN existing.system_id ELSE EXCLUDED.system_id END,
        staged_row_count = EXCLUDED.staged_row_count, is_present = true
    WHERE existing.staged_row_count IS DISTINCT FROM EXCLUDED.staged_row_count
       OR NOT existing.is_present
       OR (existing.system_assignment = 'dat' AND existing.system_id IS DISTINCT FROM EXCLUDED.system_id);
    GET DIAGNOSTICS archives_changed = ROW_COUNT;

    UPDATE public.archive a SET is_present = false, staged_row_count = 0
    WHERE a.is_present AND NOT EXISTS (
        SELECT 1 FROM _gamedb_archives live
        WHERE live.dat_id = a.dat_id AND live.archive_name_id = a.archive_name_id
    );
    GET DIAGNOSTICS archives_absent = ROW_COUNT;

    DROP TABLE _gamedb_archives;
    DROP TABLE _gamedb_dats;
    RETURN NEXT;
END;
$$;

COMMENT ON TABLE etl.system_mapping IS
    'Discovered source manufacturer/system pairs mapped to public.system IDs. Includes preserved reviewed aliases and manual decisions; do not truncate.';
COMMENT ON TABLE etl.archive_name IS
    'Persistent source-name IDs with refreshable title candidates and raw tags. Parsed fields are derived; archive references depend on these IDs.';
COMMENT ON VIEW etl.v_romset_system IS
    'etl.v_romset with canonical system IDs and display names, retaining unresolved DATs.';
COMMENT ON VIEW etl.v_archive IS
    'Current source archives, joined by IDs. Refresh with etl.refresh_archives() after staging or mapping changes.';
COMMENT ON FUNCTION etl.refresh_system_mapping() IS
    'Discover pairs from etl.v_romset; resolve exact and unique normalized names while preserving reviewed mappings.';

INSERT INTO etl.schema_migration(version) VALUES ('005_etl_schema');
COMMIT;
\endif
