\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
    IF etl.refresh_system_mapping() <> 0 THEN
        RAISE EXCEPTION 'Refresh was not idempotent; refresh the mapping before running verification';
    END IF;

    IF EXISTS (
        SELECT 1 FROM etl.v_romset r
        LEFT JOIN etl.system_mapping m USING (manufacturer, system)
        WHERE btrim(r.manufacturer) <> '' AND btrim(r.system) <> ''
          AND m.manufacturer IS NULL
    ) THEN
        RAISE EXCEPTION 'A parsed source pair is missing from system_mapping';
    END IF;

    IF (SELECT count(*) FROM etl.v_romset) <>
       (SELECT count(*) FROM etl.v_romset_system) THEN
        RAISE EXCEPTION 'Mapping changed the DAT row count';
    END IF;

    IF etl.system_name_key('MSX2') = etl.system_name_key('MSX2+')
       OR etl.system_name_key('Model') = etl.system_name_key('Model#')
       OR etl.system_name_key('TI-99/4A') <> etl.system_name_key(' ti 99-4a ') THEN
        RAISE EXCEPTION 'Name normalization discarded a significant symbol or retained a separator';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('MSX', 'MSX2', 'MSX', 'MSX2'),
            ('MSX', 'MSX2+', 'MSX', 'MSX2+'),
            ('Microsoft', 'MSX2', 'MSX', 'MSX2'),
            ('Sega', 'Mega Drive - Genesis', 'Sega', 'Mega Drive'),
            ('Nintendo', 'DS', 'Nintendo', 'Nintendo DS'),
            ('Nintendo', 'DSi', 'Nintendo', 'Nintendo DSi'),
            ('Bandai', 'Pippin', 'Apple', 'Pippin'),
            ('Commodore', 'Amiga CD', 'Commodore', 'Amiga')
        ) AS expected(manufacturer, system, canonical_manufacturer, canonical_system)
        LEFT JOIN etl.system_mapping m USING (manufacturer, system)
        LEFT JOIN public.system s ON s.id = m.system_id
        WHERE s.manufacturer_name IS DISTINCT FROM expected.canonical_manufacturer
           OR s.name IS DISTINCT FROM expected.canonical_system
    ) THEN
        RAISE EXCEPTION 'A representative alias or distinct model is mapped incorrectly';
    END IF;

    BEGIN
        INSERT INTO etl.system_mapping(manufacturer, system, system_id, match_method) VALUES
            ('__mapping_test__', 'invalid target', -1, 'manual');
        RAISE EXCEPTION 'Nonexistent canonical target was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO etl.system_mapping(manufacturer, system, system_id, match_method) VALUES
            ('__mapping_test__', 'missing target', NULL, 'manual');
        RAISE EXCEPTION 'Resolved mapping without a system ID was accepted';
    EXCEPTION WHEN check_violation OR foreign_key_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO etl.system_mapping
        SELECT * FROM etl.system_mapping WHERE manufacturer = 'Sega' AND system = 'Mega Drive - Genesis';
        RAISE EXCEPTION 'Duplicate source pair was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
END;
$$;

-- Colliding normalized names: exact spelling must still win, and a third
-- spelling must remain ambiguous rather than selecting either target.
INSERT INTO public.system(manufacturer_name, name) VALUES
    ('Mapping Test', 'Model-A'), ('Mapping Test', 'Model A');

INSERT INTO staging.rv_files (
    run_id, exported_at, tree_full_name, file_type, is_dir,
    dat_status, got_status, rep_status,
    sha1_verified, md5_verified, crc_verified, size_verified, deep_scanned,
    dat_name, dat_root_full_name
)
SELECT 'ad697971-c5d6-41c8-a26e-35ae787f8e0a'::uuid, now(),
    'DatRoot/No-Intro/' || name || '/fixture.bin', 0, false, 0, 0, 0,
    false, false, false, false, false, name, 'DatRoot/No-Intro/' || name
FROM (VALUES
    ('Mapping Test - Model_A'),
    ('Mapping Test - Model-A'),
    ('Mapping Test - Unknown'),
    ('UnparseableMappingFixture')
) AS fixtures(name);

SELECT etl.refresh_system_mapping();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM etl.system_mapping
        WHERE manufacturer = 'Mapping Test' AND system = 'Model_A'
          AND match_method = 'ambiguous' AND system_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Normalized collision was not kept ambiguous';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM etl.system_mapping
        WHERE manufacturer = 'Mapping Test' AND system = 'Model-A'
          AND match_method = 'exact' AND system_id = (SELECT id FROM public.system WHERE manufacturer_name = 'Mapping Test' AND name = 'Model-A')
    ) THEN
        RAISE EXCEPTION 'Exact match did not take priority over normalization';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM etl.system_mapping
        WHERE manufacturer = 'Mapping Test' AND system = 'Unknown'
          AND match_method = 'unmatched' AND system_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Unknown source pair was not retained';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM etl.v_romset_system
        WHERE name = 'UnparseableMappingFixture' AND match_method = 'unparsed'
    ) THEN
        RAISE EXCEPTION 'Parser failure was lost';
    END IF;
END;
$$;

UPDATE etl.system_mapping
SET system_id = (SELECT id FROM public.system WHERE manufacturer_name = 'Mapping Test' AND name = 'Model A'),
    match_method = 'manual', notes = 'Transaction-only review fixture.'
WHERE manufacturer = 'Mapping Test' AND system = 'Model_A';

INSERT INTO public.system(manufacturer_name, name) VALUES ('Mapping Test', 'Unknown');
SELECT etl.refresh_system_mapping();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM etl.system_mapping
        WHERE manufacturer = 'Mapping Test' AND system = 'Model_A'
          AND system_id = (SELECT id FROM public.system WHERE manufacturer_name = 'Mapping Test' AND name = 'Model A') AND match_method = 'manual'
    ) THEN
        RAISE EXCEPTION 'Refresh overwrote a manual decision';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM etl.system_mapping
        WHERE manufacturer = 'Mapping Test' AND system = 'Unknown'
          AND system_id = (SELECT id FROM public.system WHERE manufacturer_name = 'Mapping Test' AND name = 'Unknown') AND match_method = 'exact'
    ) THEN
        RAISE EXCEPTION 'New canonical entry did not resolve an unmatched source';
    END IF;
END;
$$;

ROLLBACK;
\echo 'System mapping verification passed; fixtures rolled back.'
