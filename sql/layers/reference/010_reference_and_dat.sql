-- Reference layer. Keep staging.rv_files; recreate maintained system
-- references and the DATs derived from the current RomVault export.
-- Run from the repository root with psql -X -v ON_ERROR_STOP=1 -f <this file>.
\set ON_ERROR_STOP on
BEGIN;

CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS derived;

-- Replacing reference identities invalidates every disposable downstream layer.
DROP SCHEMA IF EXISTS catalog CASCADE;
DROP TABLE IF EXISTS derived.archive_tag;
DROP TABLE IF EXISTS derived.archive_name_record;
DROP TABLE IF EXISTS derived.archive;
DROP TABLE IF EXISTS derived.archive_name;
DROP TABLE IF EXISTS derived.dat;
DROP TABLE IF EXISTS ref.system_mapping;
DROP TABLE IF EXISTS ref.canonical_system;

CREATE TABLE ref.canonical_system (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_manufacturer_name text NOT NULL,
    canonical_system_name text NOT NULL,
    UNIQUE (canonical_manufacturer_name, canonical_system_name),
    CHECK (btrim(canonical_manufacturer_name) <> ''),
    CHECK (btrim(canonical_system_name) <> '')
);

\copy ref.canonical_system (canonical_manufacturer_name, canonical_system_name) FROM 'data/reference/canonical_systems.csv' WITH (FORMAT csv, HEADER true)

CREATE TABLE ref.system_mapping (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    romset text NOT NULL,
    source_manufacturer text NOT NULL,
    source_system text NOT NULL,
    canonical_manufacturer text NOT NULL,
    canonical_system text NOT NULL,
    match_method text NOT NULL,
    notes text,
    UNIQUE (romset, source_manufacturer, source_system),
    FOREIGN KEY (canonical_manufacturer, canonical_system)
        REFERENCES ref.canonical_system (
            canonical_manufacturer_name, canonical_system_name
        ) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (romset IN ('No-Intro', 'Redump', 'TOSEC', 'TOSEC-ISO')),
    CHECK (match_method IN ('exact', 'normalized', 'alias', 'manual')),
    CHECK (btrim(source_manufacturer) <> ''),
    CHECK (btrim(source_system) <> '')
);

\copy ref.system_mapping (romset, source_manufacturer, source_system, canonical_manufacturer, canonical_system, match_method, notes) FROM 'data/reference/system_mappings.csv' WITH (FORMAT csv, HEADER true)

CREATE TEMP TABLE _derived_dat_source ON COMMIT DROP AS
WITH romsets AS MATERIALIZED (
    SELECT DISTINCT rf.dat_root_full_name AS dat_path, rf.dat_name
    FROM staging.rv_files rf
    WHERE rf.dat_name IS NOT NULL
), parts AS (
    SELECT r.dat_path, r.dat_name,
        (regexp_split_to_array(r.dat_path, '/'))[2:] AS path_parts,
        regexp_match(
            r.dat_name,
            '(?:(Arcade) - )?(.+?) - ([^\(]+)(?: \(([^\)]+)\))?(?: \(([^\)]+)\))?'
        ) AS name_parts
    FROM romsets r
)
SELECT p.dat_path, p.dat_name,
    p.path_parts[1] AS romset,
    CASE
        WHEN p.path_parts[1] IN ('TOSEC', 'TOSEC-ISO') THEN p.path_parts[2]
        ELSE p.name_parts[2]
    END AS source_manufacturer,
    CASE
        WHEN p.path_parts[1] IN ('TOSEC', 'TOSEC-ISO') THEN p.path_parts[3]
        ELSE p.name_parts[3]
    END AS source_system,
    CASE
        WHEN p.path_parts[1] IN ('TOSEC', 'TOSEC-ISO')
            THEN p.path_parts[4:array_length(p.path_parts, 1) - 1]
        ELSE array_remove(ARRAY[p.name_parts[1]] || p.name_parts[4:], NULL)
    END AS additional
FROM parts p
WHERE p.path_parts[1] IN ('No-Intro', 'Redump', 'TOSEC', 'TOSEC-ISO');

DO $$
DECLARE missing_count bigint;
BEGIN
    SELECT count(*) INTO missing_count
    FROM _derived_dat_source d
    LEFT JOIN ref.system_mapping m
      ON (m.romset, m.source_manufacturer, m.source_system)
       = (d.romset, d.source_manufacturer, d.source_system)
    WHERE m.id IS NULL;

    IF missing_count > 0 THEN
        RAISE EXCEPTION '% DAT rows have no entry in data/reference/system_mappings.csv',
            missing_count;
    END IF;
END;
$$;

CREATE TABLE derived.dat (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dat_path text NOT NULL,
    dat_name text NOT NULL,
    romset text NOT NULL,
    source_manufacturer text NOT NULL,
    source_system text NOT NULL,
    additional text[] NOT NULL,
    system_mapping_id bigint NOT NULL
        REFERENCES ref.system_mapping(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    canonical_system_id bigint NOT NULL
        REFERENCES ref.canonical_system(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    UNIQUE (dat_path, dat_name)
);

INSERT INTO derived.dat (
    dat_path, dat_name, romset, source_manufacturer, source_system, additional,
    system_mapping_id, canonical_system_id
)
SELECT d.dat_path, d.dat_name, d.romset, d.source_manufacturer, d.source_system,
    coalesce(d.additional, '{}'::text[]), m.id, c.id
FROM _derived_dat_source d
JOIN ref.system_mapping m
  ON (m.romset, m.source_manufacturer, m.source_system)
   = (d.romset, d.source_manufacturer, d.source_system)
JOIN ref.canonical_system c
  ON (c.canonical_manufacturer_name, c.canonical_system_name)
   = (m.canonical_manufacturer, m.canonical_system)
ORDER BY d.romset, d.source_manufacturer, d.source_system, d.dat_path, d.dat_name;

CREATE INDEX dat_canonical_system_idx ON derived.dat(canonical_system_id);
CREATE INDEX dat_mapping_idx ON derived.dat(system_mapping_id);

COMMENT ON TABLE ref.canonical_system IS
    'Maintained canonical system list loaded from data/reference/canonical_systems.csv.';
COMMENT ON TABLE ref.system_mapping IS
    'Complete maintained mapping from each RomVault collection/system triple to a canonical system.';
COMMENT ON TABLE derived.dat IS
    'Rebuildable DAT identities parsed from staging.rv_files and resolved through ref.system_mapping.';

COMMIT;
