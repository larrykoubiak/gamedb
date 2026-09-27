-- Archive names are the tagged entities, not individual files inside them.
-- Apply after the system mapping migrations, then run app.cli.parse_rv_names.
BEGIN;

CREATE TABLE IF NOT EXISTS ref.archive_name (
    romset text NOT NULL,
    archive_name text NOT NULL,
    title_candidate text NOT NULL,
    extension text NOT NULL,
    tags jsonb NOT NULL CHECK (jsonb_typeof(tags) = 'array'),
    parse_status text NOT NULL CHECK (parse_status IN ('parsed', 'review')),
    parse_issues text[] NOT NULL,
    parser_version text NOT NULL,
    parsed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (romset, archive_name),
    CHECK (btrim(archive_name) <> ''),
    CHECK ((parse_status = 'parsed') = (cardinality(parse_issues) = 0))
);

COMMENT ON TABLE ref.archive_name IS
    'Derived parse of game_display_name, once per collection and original ZIP '
    'name. This is not a canonical title or a unique archive identity. Tags are '
    'ordered, unqualified values; delimiter and character offsets preserve syntax.';

COMMENT ON COLUMN ref.archive_name.title_candidate IS
    'Provisional title after syntactic suffix extraction; never a canonical ID '
    'or an instruction to merge source entries. Inspect parse_issues.';

CREATE OR REPLACE VIEW ref.v_archive AS
WITH dats AS MATERIALIZED (
    SELECT * FROM ref.v_romset_system
), archives AS (
    SELECT rf.dat_root_full_name, rf.dat_name, rf.game_display_name,
        count(*) AS staged_row_count
    FROM staging.rv_files rf
    JOIN dats d ON d.key = rf.dat_root_full_name AND d.name = rf.dat_name
    GROUP BY rf.dat_root_full_name, rf.dat_name, rf.game_display_name
)
SELECT a.dat_root_full_name AS dat_path, a.dat_name,
    d.romset, d.manufacturer, d.system,
    d.canonical_manufacturer_name, d.canonical_system_name,
    a.game_display_name AS archive_name, a.staged_row_count,
    p.title_candidate, p.extension, p.tags,
    coalesce(p.parse_status, 'pending') AS parse_status,
    p.parse_issues, p.parser_version
FROM archives a
JOIN dats d ON d.key = a.dat_root_full_name AND d.name = a.dat_name
LEFT JOIN ref.archive_name p
    ON p.romset = d.romset AND p.archive_name = a.game_display_name;

COMMENT ON VIEW ref.v_archive IS
    'One named archive per DAT path/name, with canonical system and parsed '
    'archive name. Same names in different DATs/systems remain separate rows. '
    'staged_row_count counts export rows, including repeated export runs.';

CREATE OR REPLACE VIEW ref.v_archive_tag AS
SELECT p.romset, p.archive_name, tag.ordinality AS tag_position,
    tag.value ->> 'value' AS tag_value,
    tag.value ->> 'delimiter' AS delimiter,
    (tag.value ->> 'start')::integer AS start_offset,
    (tag.value ->> 'end')::integer AS end_offset
FROM ref.archive_name p
CROSS JOIN LATERAL jsonb_array_elements(p.tags)
    WITH ORDINALITY AS tag(value, ordinality);

CREATE OR REPLACE VIEW ref.v_archive_name_review AS
SELECT * FROM ref.archive_name WHERE parse_status = 'review';

COMMIT;
