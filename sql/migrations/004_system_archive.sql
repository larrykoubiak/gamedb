-- Upgrade the existing RomVault transforms (001-003) to persistent core IDs.
-- Apply with psql -X -v ON_ERROR_STOP=1 -f this_file.sql.
\set ON_ERROR_STOP on
BEGIN;

CREATE TABLE IF NOT EXISTS ref.schema_migration (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SELECT EXISTS (SELECT 1 FROM ref.schema_migration WHERE version = '004_system_archive') AS already_applied \gset
\if :already_applied
    \echo '004_system_archive is already applied.'
    ROLLBACK;
\else

-- Move the existing canonical records; preserve every name and mapping.
ALTER TABLE ref.canonical_system SET SCHEMA public;
ALTER TABLE public.canonical_system RENAME TO system;
ALTER TABLE public.system RENAME COLUMN canonical_manufacturer_name TO manufacturer_name;
ALTER TABLE public.system RENAME COLUMN canonical_system_name TO name;
ALTER TABLE public.system
    ALTER COLUMN manufacturer_name SET NOT NULL,
    ALTER COLUMN name SET NOT NULL,
    ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY;
COMMENT ON TABLE public.system IS 'Canonical systems. IDs are stable; display names may be edited.';

ALTER TABLE ref.system_mapping
    ADD COLUMN system_id bigint REFERENCES public.system(id) ON DELETE RESTRICT;
UPDATE ref.system_mapping m
SET system_id = s.id
FROM public.system s
WHERE s.manufacturer_name = m.canonical_manufacturer_name
  AND s.name = m.canonical_system_name;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ref.system_mapping WHERE canonical_system_name IS NOT NULL AND system_id IS NULL) THEN
        RAISE EXCEPTION 'A canonical mapping was not transferred to its system ID';
    END IF;
END;
$$;

-- Keep the existing display columns in these views, but derive them by ID.
CREATE OR REPLACE VIEW ref.v_romset_system AS
SELECT r.*, s.manufacturer_name AS canonical_manufacturer_name,
    s.name AS canonical_system_name,
    CASE WHEN nullif(btrim(r.manufacturer), '') IS NULL
           OR nullif(btrim(r.system), '') IS NULL THEN 'unparsed'
         ELSE coalesce(m.match_method, 'unmatched') END AS match_method,
    m.notes AS mapping_notes, m.system_id
FROM ref.v_romset r
LEFT JOIN ref.system_mapping m ON m.manufacturer = r.manufacturer AND m.system = r.system
LEFT JOIN public.system s ON s.id = m.system_id;

ALTER TABLE ref.system_mapping
    DROP CONSTRAINT system_mapping_canonical_manufacturer_name_canonical_syste_fkey,
    DROP CONSTRAINT system_mapping_check1,
    DROP COLUMN canonical_manufacturer_name,
    DROP COLUMN canonical_system_name,
    ADD CONSTRAINT system_mapping_target_check CHECK (
        (match_method IN ('exact', 'normalized', 'alias', 'manual') AND system_id IS NOT NULL)
        OR (match_method IN ('ambiguous', 'unmatched') AND system_id IS NULL)
    );
CREATE INDEX system_mapping_system_idx ON ref.system_mapping(system_id);

CREATE OR REPLACE FUNCTION ref.refresh_system_mapping()
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE affected_rows bigint;
BEGIN
    WITH source_pairs AS MATERIALIZED (
        SELECT DISTINCT manufacturer, system FROM ref.v_romset
        WHERE btrim(manufacturer) <> '' AND btrim(system) <> ''
    ), canonical_keys AS MATERIALIZED (
        SELECT id, ref.system_name_key(manufacturer_name) AS manufacturer_key,
            ref.system_name_key(name) AS system_key
        FROM public.system
    ), candidates AS (
        SELECT p.manufacturer, p.system, e.id AS exact_id,
            count(n.id) AS candidate_count, min(n.id) AS normalized_id
        FROM source_pairs p
        LEFT JOIN public.system e ON e.manufacturer_name = p.manufacturer AND e.name = p.system
        LEFT JOIN canonical_keys n ON n.manufacturer_key = ref.system_name_key(p.manufacturer)
                                 AND n.system_key = ref.system_name_key(p.system)
        GROUP BY p.manufacturer, p.system, e.id
    )
    INSERT INTO ref.system_mapping AS existing (manufacturer, system, system_id, match_method, notes)
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

-- A source-name identity survives changes to its derived parser output.
ALTER TABLE ref.archive_name
    ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY,
    DROP CONSTRAINT archive_name_pkey,
    ADD PRIMARY KEY (id),
    ADD CONSTRAINT archive_name_source_key UNIQUE (romset, archive_name),
    ALTER COLUMN title_candidate DROP NOT NULL,
    ALTER COLUMN extension DROP NOT NULL,
    ALTER COLUMN parser_version DROP NOT NULL,
    ALTER COLUMN parsed_at DROP NOT NULL,
    ALTER COLUMN tags SET DEFAULT '[]'::jsonb,
    ALTER COLUMN parse_status SET DEFAULT 'pending',
    ALTER COLUMN parse_issues SET DEFAULT '{}'::text[],
    DROP CONSTRAINT archive_name_parse_status_check,
    DROP CONSTRAINT archive_name_check,
    ADD CONSTRAINT archive_name_parse_status_check CHECK (parse_status IN ('pending', 'parsed', 'review')),
    ADD CONSTRAINT archive_name_issues_check CHECK (
        (parse_status = 'review' AND cardinality(parse_issues) > 0)
        OR (parse_status IN ('pending', 'parsed') AND cardinality(parse_issues) = 0)
    ),
    ADD CONSTRAINT archive_name_parsed_fields_check CHECK (
        parse_status = 'pending'
        OR (title_candidate IS NOT NULL AND extension IS NOT NULL
            AND parser_version IS NOT NULL AND parsed_at IS NOT NULL)
    );

CREATE TABLE ref.dat (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dat_path text NOT NULL,
    dat_name text NOT NULL,
    romset text NOT NULL,
    manufacturer text,
    system text,
    additional text[],
    system_id bigint REFERENCES public.system(id) ON DELETE RESTRICT,
    UNIQUE (dat_path, dat_name)
);
CREATE INDEX dat_system_idx ON ref.dat(system_id);
COMMENT ON TABLE ref.dat IS 'Source DAT identity and its default system. Source labels are retained for provenance.';

CREATE TABLE public.archive (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dat_id bigint NOT NULL REFERENCES ref.dat(id) ON DELETE RESTRICT,
    archive_name_id bigint NOT NULL REFERENCES ref.archive_name(id) ON DELETE RESTRICT,
    system_id bigint REFERENCES public.system(id) ON DELETE RESTRICT,
    system_assignment text NOT NULL DEFAULT 'dat' CHECK (system_assignment IN ('dat', 'manual')),
    staged_row_count bigint NOT NULL CHECK (staged_row_count >= 0),
    is_present boolean NOT NULL DEFAULT true,
    UNIQUE (dat_id, archive_name_id),
    CHECK (system_assignment <> 'manual' OR system_id IS NOT NULL)
);
CREATE INDEX archive_system_idx ON public.archive(system_id);
CREATE INDEX archive_name_idx ON public.archive(archive_name_id);
COMMENT ON TABLE public.archive IS
    'Persistent source archive, identified by DAT and archive-name IDs. A ZIP is '
    'not yet a canonical title or release. Manual system assignments survive '
    'refresh; absent archives retain IDs with is_present=false.';

CREATE OR REPLACE FUNCTION ref.refresh_archives()
RETURNS TABLE(dats_changed bigint, names_added bigint, archives_changed bigint, archives_absent bigint)
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('gamedb:source_sync'));
    CREATE TEMP TABLE _gamedb_dats ON COMMIT DROP AS
        SELECT * FROM ref.v_romset_system;
    ANALYZE _gamedb_dats;

    INSERT INTO ref.dat AS existing (dat_path, dat_name, romset, manufacturer, system, additional, system_id)
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
    JOIN ref.dat d ON d.dat_path = live.key AND d.dat_name = live.name
    WHERE nullif(btrim(rf.game_display_name), '') IS NOT NULL
    GROUP BY d.id, d.romset, d.system_id, rf.game_display_name;
    ANALYZE _gamedb_archive_names;

    INSERT INTO ref.archive_name (romset, archive_name, parsed_at)
    SELECT DISTINCT a.romset, a.archive_name, NULL::timestamptz
    FROM _gamedb_archive_names a
    WHERE NOT EXISTS (SELECT 1 FROM ref.archive_name p WHERE p.romset = a.romset AND p.archive_name = a.archive_name)
    ON CONFLICT (romset, archive_name) DO NOTHING;
    GET DIAGNOSTICS names_added = ROW_COUNT;

    CREATE TEMP TABLE _gamedb_archives ON COMMIT DROP AS
    SELECT a.dat_id, p.id AS archive_name_id, a.system_id, a.staged_row_count
    FROM _gamedb_archive_names a
    JOIN ref.archive_name p ON p.romset = a.romset AND p.archive_name = a.archive_name;
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

-- Existing column order is retained; IDs are appended for new consumers.
CREATE OR REPLACE VIEW ref.v_archive AS
SELECT d.dat_path, d.dat_name, d.romset, d.manufacturer, d.system,
    s.manufacturer_name AS canonical_manufacturer_name, s.name AS canonical_system_name,
    p.archive_name, a.staged_row_count, p.title_candidate, p.extension, p.tags,
    p.parse_status, p.parse_issues, p.parser_version,
    a.id AS archive_id, a.system_id, a.dat_id, a.archive_name_id
FROM public.archive a
JOIN ref.dat d ON d.id = a.dat_id
JOIN ref.archive_name p ON p.id = a.archive_name_id
LEFT JOIN public.system s ON s.id = a.system_id
WHERE a.is_present;
COMMENT ON VIEW ref.v_archive IS 'Current source archives, joined entirely by IDs. Refresh with ref.refresh_archives() after staging or mapping changes.';

CREATE OR REPLACE VIEW ref.v_archive_tag AS
SELECT p.romset, p.archive_name, tag.ordinality AS tag_position,
    tag.value ->> 'value' AS tag_value, tag.value ->> 'delimiter' AS delimiter,
    (tag.value ->> 'start')::integer AS start_offset,
    (tag.value ->> 'end')::integer AS end_offset, p.id AS archive_name_id
FROM ref.archive_name p
CROSS JOIN LATERAL jsonb_array_elements(p.tags) WITH ORDINALITY AS tag(value, ordinality);
CREATE OR REPLACE VIEW ref.v_archive_name_review AS
SELECT * FROM ref.archive_name WHERE parse_status = 'review';

SELECT * FROM ref.refresh_archives();
ANALYZE public.system;
ANALYZE ref.system_mapping;
ANALYZE ref.dat;
ANALYZE ref.archive_name;
ANALYZE public.archive;

INSERT INTO ref.schema_migration(version) VALUES ('004_system_archive');
COMMIT;
\endif
