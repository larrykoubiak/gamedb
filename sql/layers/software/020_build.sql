-- Resolve strong source identities first, then cascade them only through title
-- clusters that contain exactly one source-backed software anchor.
SET LOCAL max_parallel_workers_per_gather = 0;

-- Overrides use stable source text. Assignment creates a system-scoped manual
-- software key; exclusion leaves the selected release in a fallback group.
CREATE TEMP TABLE _software_override (
    override_ordinal bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action text NOT NULL,
    manufacturer_name text NOT NULL,
    system_name text NOT NULL,
    source_collection text NOT NULL,
    archive_name text NOT NULL,
    record_index text NOT NULL,
    target_key text,
    target_display_name text,
    note text
) ON COMMIT DROP;

\copy _software_override(action, manufacturer_name, system_name, source_collection, archive_name, record_index, target_key, target_display_name, note) FROM 'reference/software_overrides.csv' WITH (FORMAT csv, HEADER true)

DO $$
DECLARE invalid_count bigint;
BEGIN
    SELECT count(*) INTO invalid_count FROM _software_override
    WHERE action NOT IN ('assign', 'exclude')
       OR record_index !~ '^[1-9][0-9]*$'
       OR (action = 'assign' AND (
            nullif(btrim(target_key), '') IS NULL
            OR nullif(btrim(target_display_name), '') IS NULL
       ))
       OR (action = 'exclude' AND (
            nullif(btrim(target_key), '') IS NOT NULL
            OR nullif(btrim(target_display_name), '') IS NOT NULL
       ));
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% invalid software override rows', invalid_count;
    END IF;
END;
$$;

CREATE TEMP TABLE _software_override_match ON COMMIT DROP AS
SELECT DISTINCT override.override_ordinal, override.action,
    system.id AS system_id, release.id AS release_id,
    override.target_key, override.target_display_name, override.note
FROM _software_override override
JOIN catalog.system system
  ON system.manufacturer_name = override.manufacturer_name
 AND system.system_name = override.system_name
JOIN catalog.title title ON title.system_id = system.id
JOIN catalog.release release ON release.title_id = title.id
JOIN catalog.release_package membership
  ON membership.release_id = release.id
 AND membership.source_record_index = override.record_index::integer
JOIN derived.package package ON package.id = membership.package_id
JOIN derived.dat dat
  ON dat.id = package.dat_id AND dat.romset = override.source_collection
JOIN derived.archive_name archive_name
  ON archive_name.id = package.archive_name_id
 AND archive_name.archive_name = override.archive_name;

DO $$
DECLARE invalid_count bigint;
BEGIN
    SELECT count(*) INTO invalid_count FROM (
        SELECT override.override_ordinal
        FROM _software_override override
        LEFT JOIN _software_override_match match
          ON match.override_ordinal = override.override_ordinal
        GROUP BY override.override_ordinal
        HAVING count(match.release_id) <> 1
    ) invalid;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software overrides do not resolve to one release',
            invalid_count;
    END IF;
END;
$$;

CREATE TEMP TABLE _software_excluded_release ON COMMIT DROP AS
SELECT DISTINCT release_id FROM _software_override_match;

-- Strongest seed: a current release whose matching historical files all point
-- to exactly one immutable legacy software record.
CREATE TEMP TABLE _software_file_match ON COMMIT DROP AS
SELECT DISTINCT release.id AS release_id, title.system_id,
    file.id AS current_file_id,
    history_file.snapshot_key AS source_snapshot_key,
    history_release.legacy_software_id AS source_software_id,
    history_software.software_name AS source_software_name,
    history_file.legacy_release_id AS source_release_id,
    history_file.legacy_file_id AS source_file_id,
    lower(history_file.sha1_hex) AS sha1_hex
FROM catalog.release release
JOIN catalog.title title ON title.id = release.title_id
JOIN catalog.release_package membership ON membership.release_id = release.id
JOIN derived.file file ON file.package_id = membership.package_id
JOIN staging.history_legacy_file history_file
  ON lower(history_file.sha1_hex) = lower(file.sha1_hex)
JOIN staging.history_legacy_release history_release
  ON history_release.snapshot_key = history_file.snapshot_key
 AND history_release.legacy_release_id = history_file.legacy_release_id
JOIN staging.history_legacy_software history_software
  ON history_software.snapshot_key = history_release.snapshot_key
 AND history_software.legacy_software_id = history_release.legacy_software_id
LEFT JOIN _software_excluded_release excluded ON excluded.release_id = release.id
WHERE file.sha1_hex IS NOT NULL
  AND history_file.sha1_hex IS NOT NULL
  AND history_file.sha1_hex <> ''
  AND excluded.release_id IS NULL;

CREATE INDEX _software_file_match_release_idx ON _software_file_match(release_id);
ANALYZE _software_file_match;

CREATE TEMP TABLE _software_unique_assignment ON COMMIT DROP AS
SELECT release_id, min(system_id) AS system_id,
    min(source_snapshot_key) AS source_snapshot_key,
    min(source_software_id) AS source_software_id,
    min(source_software_name) AS source_software_name,
    count(*)::integer AS evidence_match_count
FROM _software_file_match GROUP BY release_id
HAVING count(DISTINCT (source_snapshot_key, source_software_id)) = 1;

CREATE TEMP TABLE _software_recovered_title ON COMMIT DROP AS
WITH title_count AS (
    SELECT assignment.system_id, assignment.source_snapshot_key,
        assignment.source_software_id, assignment.source_software_name,
        coalesce(alias.preferred_title_id, release.title_id) AS title_id,
        count(*) AS release_count
    FROM _software_unique_assignment assignment
    JOIN catalog.release release ON release.id = assignment.release_id
    LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
    GROUP BY assignment.system_id, assignment.source_snapshot_key,
        assignment.source_software_id, assignment.source_software_name,
        coalesce(alias.preferred_title_id, release.title_id)
), ranked AS (
    SELECT title_count.*,
        row_number() OVER (
            PARTITION BY title_count.system_id,
                title_count.source_snapshot_key,
                title_count.source_software_id
            ORDER BY (lower(title.display_title)
                    = lower(title_count.source_software_name)) DESC,
                title_count.release_count DESC,
                lower(title.display_title), title.display_title,
                title_count.title_id
        ) AS title_rank
    FROM title_count JOIN catalog.title title ON title.id = title_count.title_id
)
SELECT system_id, source_snapshot_key, source_software_id,
    source_software_name, title_id FROM ranked WHERE title_rank = 1;

INSERT INTO catalog.software (
    system_id, preferred_title_id, display_name, identity_basis,
    source_snapshot_key, source_software_id, source_group_key, needs_review
)
SELECT recovered.system_id, recovered.title_id,
    coalesce(nullif(btrim(recovered.source_software_name), ''), title.display_title),
    'recovered_legacy', recovered.source_snapshot_key,
    recovered.source_software_id, NULL, false
FROM _software_recovered_title recovered
JOIN catalog.title title ON title.id = recovered.title_id
ORDER BY recovered.system_id, recovered.source_snapshot_key,
    recovered.source_software_id;

INSERT INTO catalog.software_release (
    release_id, software_id, assignment_basis, evidence_match_count, needs_review
)
SELECT assignment.release_id, software.id, 'exact_sha1',
    assignment.evidence_match_count, false
FROM _software_unique_assignment assignment
JOIN catalog.software software
  ON software.system_id = assignment.system_id
 AND software.source_snapshot_key = assignment.source_snapshot_key
 AND software.source_software_id = assignment.source_software_id
ORDER BY assignment.release_id;

INSERT INTO catalog.software_release_evidence (
    software_id, release_id, evidence_type, current_file_id,
    source_snapshot_key, source_record_key, sha1_hex, details
)
SELECT membership.software_id, match.release_id, 'exact_legacy_sha1',
    match.current_file_id, match.source_snapshot_key,
    'legacy-file:' || match.source_file_id, match.sha1_hex,
    jsonb_build_object('source_software_id', match.source_software_id,
        'source_release_id', match.source_release_id,
        'source_file_id', match.source_file_id)
FROM _software_file_match match
JOIN catalog.software_release membership
  ON membership.release_id = match.release_id
 AND membership.assignment_basis = 'exact_sha1'
JOIN catalog.software software ON software.id = membership.software_id
WHERE match.source_snapshot_key = software.source_snapshot_key
  AND match.source_software_id = software.source_software_id
ORDER BY match.release_id, match.current_file_id, match.source_file_id;

-- Parent/Clone groups come from recovered DAT parent names. A release must map
-- to one group, and a group may touch at most one existing software anchor.
CREATE TEMP TABLE _parent_clone_file_match ON COMMIT DROP AS
SELECT DISTINCT release.id AS release_id, title.system_id,
    file.id AS current_file_id, dat_game.snapshot_key,
    dat_game.dat_file_id, dat_game.dat_game_id, dat_rom.dat_rom_id,
    coalesce(nullif(btrim(dat_game.clone_of), ''), dat_game.game_name) AS group_name,
    dat_game.game_name, dat_game.clone_of,
    lower(dat_rom.sha1_hex) AS sha1_hex
FROM staging.history_python_dat_rom dat_rom
JOIN staging.history_python_dat_game dat_game
  ON dat_game.snapshot_key = dat_rom.snapshot_key
 AND dat_game.dat_game_id = dat_rom.dat_game_id
JOIN derived.file file ON lower(file.sha1_hex) = lower(dat_rom.sha1_hex)
JOIN catalog.release_package package ON package.package_id = file.package_id
JOIN catalog.release release ON release.id = package.release_id
JOIN catalog.title title ON title.id = release.title_id
LEFT JOIN _software_excluded_release excluded ON excluded.release_id = release.id
WHERE dat_rom.sha1_hex IS NOT NULL AND dat_rom.sha1_hex <> ''
  AND excluded.release_id IS NULL;

CREATE INDEX _parent_clone_file_match_release_idx
    ON _parent_clone_file_match(release_id);
ANALYZE _parent_clone_file_match;

CREATE TEMP TABLE _parent_clone_eligible ON COMMIT DROP AS
SELECT match.*,
    format('dat-file:%s|parent:%s', match.dat_file_id, match.group_name)
        AS source_group_key
FROM _parent_clone_file_match match
JOIN (
    SELECT release_id FROM _parent_clone_file_match GROUP BY release_id
    HAVING count(DISTINCT (snapshot_key, dat_file_id, group_name)) = 1
) unique_group USING (release_id);

CREATE TEMP TABLE _parent_clone_group ON COMMIT DROP AS
SELECT eligible.snapshot_key, eligible.dat_file_id, eligible.group_name,
    eligible.source_group_key, eligible.system_id,
    count(DISTINCT membership.software_id) AS anchor_count,
    min(membership.software_id) AS anchor_software_id
FROM _parent_clone_eligible eligible
LEFT JOIN catalog.software_release membership
  ON membership.release_id = eligible.release_id
GROUP BY eligible.snapshot_key, eligible.dat_file_id, eligible.group_name,
    eligible.source_group_key, eligible.system_id;

CREATE TEMP TABLE _parent_clone_title ON COMMIT DROP AS
WITH title_count AS (
    SELECT group_row.snapshot_key, group_row.dat_file_id,
        group_row.group_name, group_row.source_group_key, group_row.system_id,
        coalesce(alias.preferred_title_id, release.title_id) AS title_id,
        count(*) AS release_count
    FROM _parent_clone_group group_row
    JOIN _parent_clone_eligible eligible
      ON eligible.snapshot_key = group_row.snapshot_key
     AND eligible.dat_file_id = group_row.dat_file_id
     AND eligible.group_name = group_row.group_name
     AND eligible.system_id = group_row.system_id
    JOIN catalog.release release ON release.id = eligible.release_id
    LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
    WHERE group_row.anchor_count = 0
    GROUP BY group_row.snapshot_key, group_row.dat_file_id,
        group_row.group_name, group_row.source_group_key, group_row.system_id,
        coalesce(alias.preferred_title_id, release.title_id)
), ranked AS (
    SELECT title_count.*,
        row_number() OVER (
            PARTITION BY title_count.snapshot_key,
                title_count.dat_file_id, title_count.group_name,
                title_count.system_id
            ORDER BY title_count.release_count DESC,
                lower(title.display_title), title.display_title,
                title_count.title_id
        ) AS title_rank
    FROM title_count JOIN catalog.title title ON title.id = title_count.title_id
)
SELECT * FROM ranked WHERE title_rank = 1;

INSERT INTO catalog.software (
    system_id, preferred_title_id, display_name, identity_basis,
    source_snapshot_key, source_software_id, source_group_key, needs_review
)
SELECT parent.system_id, parent.title_id, title.display_title,
    'parent_clone', parent.snapshot_key, NULL, parent.source_group_key, false
FROM _parent_clone_title parent
JOIN catalog.title title ON title.id = parent.title_id
ORDER BY parent.system_id, parent.snapshot_key, parent.source_group_key;

CREATE TEMP TABLE _parent_clone_assignment ON COMMIT DROP AS
SELECT eligible.release_id,
    coalesce(group_row.anchor_software_id, parent.id) AS software_id,
    count(*)::integer AS evidence_match_count
FROM _parent_clone_eligible eligible
JOIN _parent_clone_group group_row
  ON group_row.snapshot_key = eligible.snapshot_key
 AND group_row.dat_file_id = eligible.dat_file_id
 AND group_row.group_name = eligible.group_name
 AND group_row.system_id = eligible.system_id
LEFT JOIN catalog.software parent
  ON parent.identity_basis = 'parent_clone'
 AND parent.system_id = group_row.system_id
 AND parent.source_snapshot_key = group_row.snapshot_key
 AND parent.source_group_key = group_row.source_group_key
LEFT JOIN catalog.software_release existing ON existing.release_id = eligible.release_id
WHERE group_row.anchor_count <= 1 AND existing.release_id IS NULL
GROUP BY eligible.release_id, coalesce(group_row.anchor_software_id, parent.id);

INSERT INTO catalog.software_release (
    release_id, software_id, assignment_basis, evidence_match_count, needs_review
)
SELECT release_id, software_id, 'parent_clone', evidence_match_count, false
FROM _parent_clone_assignment ORDER BY release_id;

INSERT INTO catalog.software_release_evidence (
    software_id, release_id, evidence_type, current_file_id,
    source_snapshot_key, source_record_key, sha1_hex, details
)
SELECT assignment.software_id, eligible.release_id, 'parent_clone_sha1',
    eligible.current_file_id, eligible.snapshot_key,
    'dat-rom:' || eligible.dat_rom_id, eligible.sha1_hex,
    jsonb_build_object('dat_file_id', eligible.dat_file_id,
        'dat_game_id', eligible.dat_game_id, 'dat_rom_id', eligible.dat_rom_id,
        'group_name', eligible.group_name, 'game_name', eligible.game_name,
        'clone_of', eligible.clone_of)
FROM _parent_clone_eligible eligible
JOIN _parent_clone_assignment assignment ON assignment.release_id = eligible.release_id
ORDER BY eligible.release_id, eligible.current_file_id, eligible.dat_rom_id;

-- Explicit manual assignments override every automatic rule.
INSERT INTO catalog.software (
    system_id, preferred_title_id, display_name, identity_basis,
    source_snapshot_key, source_software_id, source_group_key, needs_review
)
SELECT match.system_id,
    min(coalesce(alias.preferred_title_id, release.title_id)),
    min(match.target_display_name), 'manual', NULL, NULL, match.target_key, false
FROM _software_override_match match
JOIN catalog.release release ON release.id = match.release_id
LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
WHERE match.action = 'assign'
GROUP BY match.system_id, match.target_key
ORDER BY match.system_id, match.target_key;

INSERT INTO catalog.software_release (
    release_id, software_id, assignment_basis, evidence_match_count, needs_review
)
SELECT match.release_id, software.id, 'manual_override', 1, false
FROM _software_override_match match
JOIN catalog.software software
  ON software.identity_basis = 'manual'
 AND software.system_id = match.system_id
 AND software.source_group_key = match.target_key
WHERE match.action = 'assign' ORDER BY match.release_id;

INSERT INTO catalog.software_release_evidence (
    software_id, release_id, evidence_type, current_file_id,
    source_snapshot_key, source_record_key, sha1_hex, details
)
SELECT membership.software_id, match.release_id, 'manual_override',
    NULL, NULL, match.target_key, NULL, jsonb_build_object('note', match.note)
FROM _software_override_match match
JOIN catalog.software_release membership ON membership.release_id = match.release_id
WHERE match.action = 'assign';

-- Maybe-Intro marks localized archive titles with [n], while the playable
-- member retains the original title. Attach such a translation only when that
-- original title has exactly one already evidence-backed software anchor.
CREATE TEMP TABLE _translation_original_release ON COMMIT DROP AS
SELECT release.id AS release_id, title.system_id,
    min(member_title.title_text) AS original_title,
    count(DISTINCT file.id)::integer AS evidence_match_count
FROM catalog.release release
JOIN catalog.title title ON title.id = release.title_id
JOIN catalog.release_package release_package
  ON release_package.release_id = release.id
JOIN derived.package package ON package.id = release_package.package_id
JOIN derived.dat dat
  ON dat.id = package.dat_id AND dat.romset = 'English Translations'
JOIN derived.file file ON file.package_id = package.id
JOIN derived.translation_member_title member_title
  ON member_title.file_id = file.id AND member_title.parse_status = 'parsed'
JOIN derived.assertion localized
  ON localized.archive_name_id = release_package.source_archive_name_id
 AND localized.record_index = release_package.source_record_index
 AND localized.assertion_key = 'special'
 AND localized.assertion_value = 'localized_title'
LEFT JOIN catalog.software_release existing ON existing.release_id = release.id
LEFT JOIN _software_excluded_release excluded ON excluded.release_id = release.id
WHERE existing.release_id IS NULL AND excluded.release_id IS NULL
GROUP BY release.id, title.system_id
HAVING count(DISTINCT member_title.title_text) = 1
   AND min(member_title.title_text) <> min(title.cluster_key);

CREATE TEMP TABLE _translation_original_assignment ON COMMIT DROP AS
WITH target_title AS (
    SELECT original.release_id, original.original_title,
        original.evidence_match_count,
        coalesce(alias.preferred_title_id, title.id) AS effective_title_id
    FROM _translation_original_release original
    JOIN catalog.title title
      ON title.system_id = original.system_id
     AND title.cluster_key = original.original_title
    LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = title.id
), target_anchor AS (
    SELECT coalesce(alias.preferred_title_id, release.title_id) AS effective_title_id,
        count(DISTINCT membership.software_id) AS anchor_count,
        min(membership.software_id) AS software_id
    FROM catalog.release release
    LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
    JOIN catalog.software_release membership ON membership.release_id = release.id
    GROUP BY coalesce(alias.preferred_title_id, release.title_id)
)
SELECT target.release_id, anchor.software_id, target.original_title,
    target.evidence_match_count
FROM target_title target
JOIN target_anchor anchor
  ON anchor.effective_title_id = target.effective_title_id
 AND anchor.anchor_count = 1;

INSERT INTO catalog.software_release (
    release_id, software_id, assignment_basis, evidence_match_count, needs_review
)
SELECT release_id, software_id, 'translation_original_title',
    evidence_match_count, true
FROM _translation_original_assignment ORDER BY release_id;

INSERT INTO catalog.software_release_evidence (
    software_id, release_id, evidence_type, current_file_id,
    source_snapshot_key, source_record_key, sha1_hex, details
)
SELECT assignment.software_id, assignment.release_id,
    'translation_member_title', file.id, NULL,
    'translation-member:' || file.id, lower(file.sha1_hex),
    jsonb_build_object(
        'original_title', assignment.original_title,
        'member_name', file.file_name,
        'source_collection', dat.romset,
        'localized_title_marker', '[n]'
    )
FROM _translation_original_assignment assignment
JOIN catalog.release_package release_package
  ON release_package.release_id = assignment.release_id
JOIN derived.package package ON package.id = release_package.package_id
JOIN derived.dat dat
  ON dat.id = package.dat_id AND dat.romset = 'English Translations'
JOIN derived.file file ON file.package_id = package.id
JOIN derived.translation_member_title member_title
  ON member_title.file_id = file.id
 AND member_title.parse_status = 'parsed'
 AND member_title.title_text = assignment.original_title
ORDER BY assignment.release_id, file.id;

-- Restore the downward cascade from the former title pass. It stops whenever
-- an effective title contains more than one source-backed software anchor.
CREATE TEMP TABLE _software_title_anchor ON COMMIT DROP AS
SELECT coalesce(alias.preferred_title_id, release.title_id) AS title_id,
    count(DISTINCT membership.software_id) AS anchor_count,
    min(membership.software_id) AS software_id
FROM catalog.release release
LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
JOIN catalog.software_release membership ON membership.release_id = release.id
GROUP BY coalesce(alias.preferred_title_id, release.title_id);

CREATE TEMP TABLE _software_title_assignment ON COMMIT DROP AS
SELECT release.id AS release_id, anchor.software_id, anchor.title_id,
    title.cluster_key
FROM catalog.release release
LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
JOIN _software_title_anchor anchor
  ON anchor.title_id = coalesce(alias.preferred_title_id, release.title_id)
 AND anchor.anchor_count = 1
JOIN catalog.title title ON title.id = anchor.title_id
LEFT JOIN catalog.software_release existing ON existing.release_id = release.id
LEFT JOIN _software_excluded_release excluded ON excluded.release_id = release.id
WHERE existing.release_id IS NULL AND excluded.release_id IS NULL;

INSERT INTO catalog.software_release (
    release_id, software_id, assignment_basis, evidence_match_count, needs_review
)
SELECT release_id, software_id, 'anchored_title', 1, true
FROM _software_title_assignment ORDER BY release_id;

INSERT INTO catalog.software_release_evidence (
    software_id, release_id, evidence_type, current_file_id,
    source_snapshot_key, source_record_key, sha1_hex, details
)
SELECT software_id, release_id, 'anchored_title', NULL, NULL,
    cluster_key, NULL, jsonb_build_object('effective_title_id', title_id)
FROM _software_title_assignment ORDER BY release_id;

-- Keep unsafe Parent/Clone relationships and recovered human reviews visible.
INSERT INTO catalog.software_identity_candidate (
    candidate_type, review_status, system_id,
    source_snapshot_key, source_record_key, details
)
SELECT 'parent_clone_conflict', 'pending', system_id, snapshot_key,
    source_group_key, jsonb_build_object('dat_file_id', dat_file_id,
        'group_name', group_name, 'anchor_count', anchor_count)
FROM _parent_clone_group WHERE anchor_count > 1;

INSERT INTO catalog.software_identity_candidate (
    candidate_type, review_status, system_id,
    source_snapshot_key, source_record_key, details
)
SELECT 'parent_clone_ambiguous_release', 'pending', min(system_id),
    min(snapshot_key), 'current-release:' || release_id,
    jsonb_build_object('release_id', release_id,
        'group_count', count(DISTINCT (snapshot_key, dat_file_id, group_name)))
FROM _parent_clone_file_match GROUP BY release_id
HAVING count(DISTINCT (snapshot_key, dat_file_id, group_name)) > 1;

INSERT INTO catalog.software_identity_candidate (
    candidate_type, review_status, system_id,
    source_snapshot_key, source_record_key, details
)
SELECT CASE review.review_decision
        WHEN 'accepted' THEN 'reviewed_external_match'
        ELSE 'reviewed_external_rejection' END,
    review.review_decision, system.id, review.snapshot_key,
    'match-review-row:' || review.row_number,
    jsonb_build_object('historical_system', review.system_name,
        'software_name', review.software_name,
        'normalized_software_name', review.normalized_software_name,
        'matched_external_name', review.matched_external_name,
        'match_method', review.match_method,
        'original_score', review.original_score,
        'reviewed_score', review.reviewed_score,
        'external_url', review.external_url,
        'external_identifiers', coalesce(external.identifiers, '[]'::jsonb))
FROM staging.history_match_review review
LEFT JOIN catalog.system system
  ON lower(system.manufacturer_name || ' - ' || system.system_name)
     = lower(review.system_name)
LEFT JOIN LATERAL (
    SELECT jsonb_agg(DISTINCT jsonb_build_object(
        'external_game_id', map.right_id,
        'source_name', game.source_name,
        'game_name', game.game_name,
        'game_url', game.game_url
    )) AS identifiers
    FROM staging.history_python_system history_system
    JOIN staging.history_python_software history_software
      ON history_software.snapshot_key = history_system.snapshot_key
     AND history_software.legacy_system_id = history_system.legacy_system_id
     AND history_software.software_name = review.software_name
    JOIN staging.history_python_map map
      ON map.snapshot_key = history_software.snapshot_key
     AND map.map_type = 'software_external'
     AND map.left_id = history_software.legacy_software_id
    LEFT JOIN staging.history_python_external_game game
      ON game.snapshot_key = map.snapshot_key
     AND game.external_game_id = map.right_id
    WHERE lower(history_system.manufacturer_name || ' - '
        || history_system.system_name) = lower(review.system_name)
) external ON true
WHERE review.review_decision IN ('accepted', 'rejected')
ORDER BY review.row_number;

-- Every remaining release gets an explicit unresolved title fallback.
INSERT INTO catalog.software (
    system_id, preferred_title_id, display_name, identity_basis,
    source_snapshot_key, source_software_id, source_group_key, needs_review
)
SELECT title.system_id, effective.title_id, title.display_title,
    'title_fallback', NULL, NULL, NULL, true
FROM (
    SELECT DISTINCT coalesce(alias.preferred_title_id, release.title_id) AS title_id
    FROM catalog.release release
    LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
    LEFT JOIN catalog.software_release membership ON membership.release_id = release.id
    WHERE membership.release_id IS NULL
) effective
JOIN catalog.title title ON title.id = effective.title_id
ORDER BY title.system_id, lower(title.display_title), title.display_title,
    effective.title_id;

INSERT INTO catalog.software_release (
    release_id, software_id, assignment_basis, evidence_match_count, needs_review
)
SELECT release.id, software.id, 'title_fallback', 0, true
FROM catalog.release release
LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id
JOIN catalog.software software
  ON software.identity_basis = 'title_fallback'
 AND software.preferred_title_id = coalesce(alias.preferred_title_id, release.title_id)
LEFT JOIN catalog.software_release existing ON existing.release_id = release.id
WHERE existing.release_id IS NULL ORDER BY release.id;

-- Working app corrections are durable but provisional. Promoted reference
-- decisions take precedence for the same system/content subject. Signatures
-- identify complete release content, so every duplicate source occurrence is
-- moved together.
CREATE TEMP TABLE _active_content_correction ON COMMIT DROP AS
SELECT NULL::bigint AS working_id, 'reference'::text AS source_kind,
    correction.manufacturer_name, correction.system_name,
    correction.subject_content_signature, correction.action,
    correction.target_content_signature, correction.note
FROM ref.software_correction correction
UNION ALL
SELECT correction.id, 'working', correction.manufacturer_name,
    correction.system_name, correction.subject_content_signature,
    correction.action, correction.target_content_signature, correction.note
FROM app.software_correction correction
WHERE correction.status = 'active'
  AND NOT EXISTS (
      SELECT 1 FROM ref.software_correction reviewed
      WHERE reviewed.manufacturer_name = correction.manufacturer_name
        AND reviewed.system_name = correction.system_name
        AND reviewed.subject_content_signature
            = correction.subject_content_signature
  );

DO $$
DECLARE invalid_count bigint;
BEGIN
    SELECT count(*) INTO invalid_count
    FROM _active_content_correction correction
    LEFT JOIN catalog.system system
      ON system.manufacturer_name = correction.manufacturer_name
     AND system.system_name = correction.system_name
    WHERE system.id IS NULL;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software corrections reference an unknown system',
            invalid_count;
    END IF;

    SELECT count(*) INTO invalid_count
    FROM _active_content_correction correction
    JOIN catalog.system system
      ON system.manufacturer_name = correction.manufacturer_name
     AND system.system_name = correction.system_name
    WHERE NOT EXISTS (
        SELECT 1
        FROM catalog.release_content_signature signature
        JOIN catalog.release release ON release.id = signature.release_id
        JOIN catalog.title title ON title.id = release.title_id
        WHERE title.system_id = system.id
          AND signature.sha1_set_digest
              = correction.subject_content_signature
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software correction subjects do not resolve',
            invalid_count;
    END IF;

    SELECT count(*) INTO invalid_count
    FROM _active_content_correction correction
    JOIN catalog.system system
      ON system.manufacturer_name = correction.manufacturer_name
     AND system.system_name = correction.system_name
    WHERE correction.action = 'assign' AND NOT EXISTS (
        SELECT 1
        FROM catalog.release_content_signature signature
        JOIN catalog.release release ON release.id = signature.release_id
        JOIN catalog.title title ON title.id = release.title_id
        WHERE title.system_id = system.id
          AND signature.sha1_set_digest
              = correction.target_content_signature
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software correction targets do not resolve',
            invalid_count;
    END IF;

    SELECT count(*) INTO invalid_count
    FROM _active_content_correction correction
    WHERE correction.action = 'assign' AND EXISTS (
        SELECT 1 FROM _active_content_correction target
        WHERE target.manufacturer_name = correction.manufacturer_name
          AND target.system_name = correction.system_name
          AND target.subject_content_signature
              = correction.target_content_signature
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software corrections form chains or cycles',
            invalid_count;
    END IF;
END;
$$;

CREATE TEMP TABLE _resolved_content_correction ON COMMIT DROP AS
SELECT correction.*, system.id AS system_id,
    CASE WHEN correction.action = 'assign'
        THEN target.target_software_id END AS target_software_id
FROM _active_content_correction correction
JOIN catalog.system system
  ON system.manufacturer_name = correction.manufacturer_name
 AND system.system_name = correction.system_name
LEFT JOIN LATERAL (
    SELECT min(membership.software_id) AS target_software_id,
        count(DISTINCT membership.software_id) AS software_count
    FROM catalog.release_content_signature signature
    JOIN catalog.release release ON release.id = signature.release_id
    JOIN catalog.title title
      ON title.id = release.title_id AND title.system_id = system.id
    JOIN catalog.software_release membership
      ON membership.release_id = release.id
    WHERE signature.sha1_set_digest = correction.target_content_signature
) target ON correction.action = 'assign'
WHERE correction.action = 'separate' OR target.software_count = 1;

DO $$
DECLARE invalid_count bigint;
BEGIN
    SELECT count(*) INTO invalid_count FROM _active_content_correction;
    SELECT invalid_count - count(*) INTO invalid_count
    FROM _resolved_content_correction;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION '% software correction targets span multiple software identities',
            invalid_count;
    END IF;
END;
$$;

CREATE TEMP TABLE _content_correction_subject ON COMMIT DROP AS
SELECT correction.*, release.id AS release_id,
    coalesce(alias.preferred_title_id, release.title_id) AS effective_title_id
FROM _resolved_content_correction correction
JOIN catalog.release_content_signature signature
  ON signature.sha1_set_digest = correction.subject_content_signature
JOIN catalog.release release ON release.id = signature.release_id
JOIN catalog.title title
  ON title.id = release.title_id AND title.system_id = correction.system_id
LEFT JOIN catalog.title_alias alias ON alias.alias_title_id = release.title_id;

INSERT INTO catalog.software (
    system_id, preferred_title_id, display_name, identity_basis,
    source_snapshot_key, source_software_id, source_group_key, needs_review
)
SELECT subject.system_id, min(subject.effective_title_id),
    min(title.display_title), 'manual', NULL, NULL,
    'content-correction:' || subject.subject_content_signature, false
FROM _content_correction_subject subject
JOIN catalog.title title ON title.id = subject.effective_title_id
WHERE subject.action = 'separate'
GROUP BY subject.system_id, subject.subject_content_signature
ORDER BY subject.system_id, subject.subject_content_signature;

CREATE TEMP TABLE _content_correction_assignment ON COMMIT DROP AS
SELECT subject.release_id, subject.subject_content_signature,
    subject.target_content_signature, subject.source_kind,
    subject.working_id, subject.action, subject.note,
    coalesce(subject.target_software_id, separate.id) AS software_id
FROM _content_correction_subject subject
LEFT JOIN catalog.software separate
  ON separate.identity_basis = 'manual'
 AND separate.system_id = subject.system_id
 AND separate.source_group_key
     = 'content-correction:' || subject.subject_content_signature;

DELETE FROM catalog.software_release membership
USING _content_correction_assignment assignment
WHERE membership.release_id = assignment.release_id;

INSERT INTO catalog.software_release (
    release_id, software_id, assignment_basis, evidence_match_count, needs_review
)
SELECT release_id, software_id, 'manual_correction', 1, false
FROM _content_correction_assignment ORDER BY release_id;

INSERT INTO catalog.software_release_evidence (
    software_id, release_id, evidence_type, current_file_id,
    source_snapshot_key, source_record_key, sha1_hex, details
)
SELECT software_id, release_id, 'manual_content_correction', NULL, NULL,
    source_kind || ':content-correction:' || subject_content_signature,
    NULL, jsonb_build_object(
        'subject_content_signature', subject_content_signature,
        'target_content_signature', target_content_signature,
        'action', action,
        'working_correction_id', working_id,
        'note', note
    )
FROM _content_correction_assignment ORDER BY release_id;

DELETE FROM catalog.software software
WHERE NOT EXISTS (
    SELECT 1 FROM catalog.software_release membership
    WHERE membership.software_id = software.id
);
