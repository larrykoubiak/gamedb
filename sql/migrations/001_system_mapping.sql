-- Historical migration: see ../README.md for prerequisites and upgrade order.
-- Run with psql -X -v ON_ERROR_STOP=1 -f sql/migrations/001_system_mapping.sql.
-- Requires the existing staging.rv_files, ref.v_romset and ref.canonical_system.
-- Safe to rerun: existing mapping decisions take precedence over seed/defaults.
-- Then apply 002_nec_system_mapping.sql for the reviewed NEC mappings.
BEGIN;

-- A canonical name pair is the existing system identity; no new IDs are needed.
CREATE UNIQUE INDEX IF NOT EXISTS canonical_system_names_uidx
    ON ref.canonical_system (canonical_manufacturer_name, canonical_system_name);

CREATE OR REPLACE FUNCTION ref.system_name_key(value text)
RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$
    -- Ignore case and common separators, but retain meaningful symbols such as
    -- '+' (MSX2 versus MSX2+), '#' and '@'. Never remove words or model numbers.
    SELECT lower(regexp_replace(value, '[[:space:].,/&''_-]+', '', 'g'));
$$;

CREATE TABLE IF NOT EXISTS ref.system_mapping (
    manufacturer text NOT NULL,
    system text NOT NULL,
    canonical_manufacturer_name varchar(50),
    canonical_system_name varchar(50),
    match_method text NOT NULL,
    notes text,
    PRIMARY KEY (manufacturer, system),
    FOREIGN KEY (canonical_manufacturer_name, canonical_system_name)
        REFERENCES ref.canonical_system
            (canonical_manufacturer_name, canonical_system_name)
        MATCH FULL ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (btrim(manufacturer) <> '' AND btrim(system) <> ''),
    CHECK (match_method IN
        ('exact', 'normalized', 'alias', 'manual', 'ambiguous', 'unmatched')),
    CHECK (
        (match_method IN ('exact', 'normalized', 'alias', 'manual')
            AND canonical_manufacturer_name IS NOT NULL
            AND canonical_system_name IS NOT NULL)
        OR
        (match_method IN ('ambiguous', 'unmatched')
            AND canonical_manufacturer_name IS NULL
            AND canonical_system_name IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS system_mapping_canonical_idx
    ON ref.system_mapping (canonical_manufacturer_name, canonical_system_name);

COMMENT ON TABLE ref.system_mapping IS
    'Parsed ref.v_romset manufacturer/system aliases to canonical systems. '
    'Source strings are preserved; ambiguous and unmatched rows have no target.';

-- Reviewed aliases and family groupings, following the supplied canonical list.
-- Cross-manufacturer choices apply only to the named system (not globally).
INSERT INTO ref.system_mapping
    (manufacturer, system, canonical_manufacturer_name, canonical_system_name,
     match_method, notes)
VALUES
    ('3DO', '3DO Interactive Multiplayer', 'The 3DO Company', '3DO Interactive Multiplayer', 'alias', 'Canonical manufacturer attribution.'),
    ('Altos Computer Systems', 'ACS-186, 586, 686 & 986', 'Altos Computer Systems', 'ACS series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Atari', '2600 & VCS', 'Atari', '2600', 'alias', 'VCS is the alternative name for the Atari 2600.'),
    ('Atari', '8-bit Family', 'Atari', '8-bit computers', 'alias', 'Canonical Atari 8-bit family.'),
    ('Atari', '8bit', 'Atari', '8-bit computers', 'alias', 'Canonical Atari 8-bit family.'),
    ('Bally', 'Professional Arcade & Astrocade', 'Bally', 'Astrocade', 'alias', 'Alternative system names.'),
    ('Bandai', 'Pippin', 'Apple', 'Pippin', 'alias', 'Canonical list attributes the Pippin platform to Apple.'),
    ('Bandai', 'Pippin @World & Pippin Atmark', 'Apple', 'Pippin', 'alias', 'Regional Pippin names; canonical manufacturer is Apple.'),
    ('Bandai', 'Playdia Quick Interactive System', 'Bandai', 'Playdia', 'alias', 'Expanded system name.'),
    ('Casio', 'FP-1000 & FP-1100', 'Casio', 'FP-1000 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Commodore', 'Amiga CD', 'Commodore', 'Amiga', 'alias', 'CD media for Amiga computers; CD32 and CDTV have separate canonical entries.'),
    ('Commodore', 'C16, C116 & Plus-4', 'Commodore', '264 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Commodore', 'Commodore 64', 'Commodore', 'C64', 'alias', 'Expanded system name.'),
    ('Commodore', 'Plus-4', 'Commodore', '264 series', 'alias', 'Model grouped into the supplied canonical family.'),
    ('Creatronic', 'Mega Duck & Cougar Boy', 'Welback', 'Mega Duck / Cougar Boy', 'alias', 'Alternative branding; follows the supplied Welback attribution.'),
    ('Dick Smith', 'Super-80, Super-80D, Super-80E & Super-80M', 'Dick Smith', 'Super-80 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Dick Smith', 'Super-80R & Super-80V', 'Dick Smith', 'Super-80 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Elektronska Industrija Nis', 'PECOM 32 & 64', 'Elektronska Industrija Nis', 'PECOM', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Enterprise', '64 & 128', 'Enterprise', 'Enterprise', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Fairchild', 'VES & Channel F', 'Fairchild', 'Channel F', 'alias', 'Alternative system names.'),
    ('LeapFrog', 'Leapster Learning Game System', 'LeapFrog', 'Leapster', 'alias', 'Expanded system name.'),
    ('Microsoft', 'MSX', 'MSX', 'MSX', 'alias', 'Canonical list uses MSX as manufacturer for the standard.'),
    ('Microsoft', 'MSX2', 'MSX', 'MSX2', 'alias', 'Canonical list uses MSX as manufacturer for the standard.'),
    ('Nascom', 'I & II', 'Nascom', 'Nascom', 'alias', 'Models grouped into the supplied canonical family.'),
    ('NEC', 'PC-Engine CD & TurboGrafx-16 CD', 'NEC', 'PC Engine CD / TurboGrafx-CD', 'alias', 'Regional system names.'),
    ('NEC', 'PC Engine SuperGrafx', 'NEC', 'SuperGrafx', 'alias', 'Expanded system name; distinct from PC Engine.'),
    ('Nintendo', '64', 'Nintendo', 'Nintendo 64', 'alias', 'Canonical name includes manufacturer.'),
    ('Nintendo', '64DD', 'Nintendo', 'Nintendo 64DD', 'alias', 'Canonical name includes manufacturer; distinct from Nintendo 64.'),
    ('Nintendo', 'DS', 'Nintendo', 'Nintendo DS', 'alias', 'Canonical name includes manufacturer.'),
    ('Nintendo', 'DSi', 'Nintendo', 'Nintendo DSi', 'alias', 'Canonical name includes manufacturer; distinct from Nintendo DS.'),
    ('Nintendo', 'Famicom & Entertainment System', 'Nintendo', 'Nintendo Entertainment System', 'alias', 'Regional system names.'),
    ('Nintendo', 'Family Computer Disk System', 'Nintendo', 'Famicom Disk System', 'alias', 'Expanded system name.'),
    ('Nintendo', 'Super Famicom & Super Entertainment System', 'Nintendo', 'Super Nintendo Entertainment System', 'alias', 'Regional system names.'),
    ('Nuclear Data', 'ND4410 & ND4420', 'Nuclear Data', 'ND4400 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('OCC', 'Osborne 1 & Osborne Executive', 'OCC', 'Osborne 1 / Executive', 'alias', 'Alternative family spelling.'),
    ('Panasonic', '3DO Interactive Multiplayer', 'The 3DO Company', '3DO Interactive Multiplayer', 'alias', 'Canonical manufacturer attribution.'),
    ('Robotron', 'HC900, KC85 2, KC85 3 & KC85 4', 'Robotron', 'KC 85 family', 'alias', 'Models grouped into the supplied canonical family; Z9001 / KC 85/1 stays separate.'),
    ('Sanyo', 'MBC-550 & 555', 'Sanyo', 'MBC-550 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Sega', 'Advanced Pico Beena', 'Sega', 'Beena', 'alias', 'Expanded system name; distinct from Pico.'),
    ('Sega', 'Game 1000', 'Sega', 'SG-1000', 'alias', 'Sega Game 1000 abbreviation: https://www.smspower.org/'),
    ('Sega', 'Mark III & Master System', 'Sega', 'Master System', 'alias', 'Regional system names.'),
    ('Sega', 'Master System - Mark III', 'Sega', 'Master System', 'alias', 'Regional system names.'),
    ('Sega', 'Mega CD & Sega CD', 'Sega', 'Mega-CD', 'alias', 'Regional system names.'),
    ('Sega', 'Mega-CD & Sega CD', 'Sega', 'Mega-CD', 'alias', 'Regional system names.'),
    ('Sega', 'Mega Drive & Genesis', 'Sega', 'Mega Drive', 'alias', 'Regional system names.'),
    ('Sega', 'Mega Drive - Genesis', 'Sega', 'Mega Drive', 'alias', 'Regional system names.'),
    ('Sharp', 'MZ-2000 & MZ-2200', 'Sharp', 'MZ-2000 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Sharp', 'PC-G850, PC-G815 & E200', 'Sharp', 'PC-G / E200 family', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Sinclair', 'ZX Spectrum +3', 'Sinclair', 'ZX Spectrum', 'alias', 'Model grouped into the supplied canonical family.'),
    ('Tangerine', 'Oric-1 & Oric Atmos', 'Tangerine', 'Oric', 'alias', 'Models grouped into the supplied canonical family.'),
    ('TeleVideo Systems', 'TS-802 & TS-802H', 'TeleVideo Systems', 'TS-802 series', 'alias', 'Models grouped into the supplied canonical family.'),
    ('TeleVideo Systems', 'TS-803, TS-803H & TPC-1', 'TeleVideo Systems', 'TS-803 / TPC-1 family', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Thomson', 'TO8, TO8D, TO9, TO9+', 'Thomson', 'TO8 / TO9 family', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Tiger', 'Game.com', 'Tiger Electronics', 'Game.com', 'alias', 'Expanded manufacturer name.'),
    ('VTech', 'Laser 350, 500, 700 & 750', 'VTech', 'Laser 350/500/700/750 family', 'alias', 'Models grouped into the supplied canonical family.'),
    ('Welback', 'Mega Duck', 'Welback', 'Mega Duck / Cougar Boy', 'alias', 'Regional system names.'),
    ('NEC', 'PC-88 series', NULL, NULL, 'ambiguous', 'Source label does not distinguish canonical PC-8801 from PC-88VA. Requires a family policy or per-game mapping.'),
    ('NEC', 'PC-98 series', NULL, NULL, 'ambiguous', 'Source label does not distinguish canonical PC-9801 from PC-9821. Requires a family policy or per-game mapping.'),
    ('NEC', 'PC-FX & PC-FXGA', NULL, NULL, 'ambiguous', 'Source combines two distinct canonical systems, PC-FX and PC-FXGA. Requires a family policy or per-game mapping.')
ON CONFLICT (manufacturer, system) DO NOTHING;

CREATE OR REPLACE FUNCTION ref.refresh_system_mapping()
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    affected_rows bigint;
BEGIN
    WITH source_pairs AS MATERIALIZED (
        SELECT DISTINCT manufacturer, system
        FROM ref.v_romset
        WHERE btrim(manufacturer) <> '' AND btrim(system) <> ''
    ), canonical_keys AS MATERIALIZED (
        SELECT c.*,
            ref.system_name_key(canonical_manufacturer_name) AS manufacturer_key,
            ref.system_name_key(canonical_system_name) AS system_key
        FROM ref.canonical_system c
        WHERE canonical_manufacturer_name IS NOT NULL
          AND canonical_system_name IS NOT NULL
    ), candidates AS (
        SELECT s.manufacturer, s.system,
            e.canonical_manufacturer_name AS exact_manufacturer,
            e.canonical_system_name AS exact_system,
            count(n.canonical_system_name) AS candidate_count,
            min(n.canonical_manufacturer_name) AS normalized_manufacturer,
            min(n.canonical_system_name) AS normalized_system
        FROM source_pairs s
        LEFT JOIN ref.canonical_system e
            ON e.canonical_manufacturer_name = s.manufacturer
           AND e.canonical_system_name = s.system
        LEFT JOIN canonical_keys n
            ON n.manufacturer_key = ref.system_name_key(s.manufacturer)
           AND n.system_key = ref.system_name_key(s.system)
        GROUP BY s.manufacturer, s.system,
                 e.canonical_manufacturer_name, e.canonical_system_name
    )
    INSERT INTO ref.system_mapping AS existing
        (manufacturer, system, canonical_manufacturer_name, canonical_system_name,
         match_method, notes)
    SELECT manufacturer, system,
        CASE WHEN exact_system IS NOT NULL THEN exact_manufacturer
             WHEN candidate_count = 1 THEN normalized_manufacturer END,
        CASE WHEN exact_system IS NOT NULL THEN exact_system
             WHEN candidate_count = 1 THEN normalized_system END,
        CASE WHEN exact_system IS NOT NULL THEN 'exact'
             WHEN candidate_count = 1 THEN 'normalized'
             WHEN candidate_count > 1 THEN 'ambiguous'
             ELSE 'unmatched' END,
        CASE WHEN exact_system IS NOT NULL THEN NULL
             WHEN candidate_count = 1 THEN 'Case, whitespace or separator variation.'
             WHEN candidate_count > 1 THEN 'Multiple canonical pairs share this normalized name; review required.'
             ELSE 'No canonical name match; add an explicit alias or canonical system.' END
    FROM candidates
    ON CONFLICT (manufacturer, system) DO UPDATE
    SET canonical_manufacturer_name = EXCLUDED.canonical_manufacturer_name,
        canonical_system_name = EXCLUDED.canonical_system_name,
        match_method = EXCLUDED.match_method,
        notes = EXCLUDED.notes
    -- New canonical entries may resolve an unknown pair. Preserve every existing
    -- resolution and review decision, including user edits and curated aliases.
    WHERE existing.match_method = 'unmatched'
      AND EXCLUDED.match_method IN ('exact', 'normalized');

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows;
END;
$$;

COMMENT ON FUNCTION ref.refresh_system_mapping() IS
    'Discover source pairs from ref.v_romset. Match exact names, then unique '
    'normalized canonical names. Preserve existing mapping decisions. '
    'Returns the number of inserted or newly resolved pairs.';

SELECT ref.refresh_system_mapping();

CREATE OR REPLACE VIEW ref.v_romset_system AS
SELECT r.*,
    m.canonical_manufacturer_name,
    m.canonical_system_name,
    CASE WHEN nullif(btrim(r.manufacturer), '') IS NULL
           OR nullif(btrim(r.system), '') IS NULL THEN 'unparsed'
         ELSE coalesce(m.match_method, 'unmatched') END AS match_method,
    m.notes AS mapping_notes
FROM ref.v_romset r
LEFT JOIN ref.system_mapping m
    ON m.manufacturer = r.manufacturer AND m.system = r.system;

COMMENT ON VIEW ref.v_romset_system IS
    'ref.v_romset with canonical system mapping; retains all DAT rows, including '
    'unresolved ones. Join rv_files using BOTH dat_root_full_name = key and '
    'dat_name = name, since v_romset is distinct on that pair.';

CREATE OR REPLACE VIEW ref.v_system_mapping_review AS
SELECT manufacturer, system, match_method, mapping_notes,
    array_agg(DISTINCT romset ORDER BY romset) AS romsets,
    count(*) AS dat_count
FROM ref.v_romset_system
WHERE canonical_system_name IS NULL
GROUP BY manufacturer, system, match_method, mapping_notes;

COMMIT;
