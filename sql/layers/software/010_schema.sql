-- Build the software identity boundary between source-facing releases and
-- consumer scoring. Historical records are evidence, never canonical owners.
\set ON_ERROR_STOP on
BEGIN;

CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE IF NOT EXISTS app.software_correction (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    manufacturer_name text NOT NULL CHECK (btrim(manufacturer_name) <> ''),
    system_name text NOT NULL CHECK (btrim(system_name) <> ''),
    subject_content_signature text NOT NULL
        CHECK (subject_content_signature ~ '^[0-9a-f]{32}$'),
    action text NOT NULL CHECK (action IN ('assign', 'separate')),
    target_content_signature text
        CHECK (target_content_signature IS NULL
            OR target_content_signature ~ '^[0-9a-f]{32}$'),
    note text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'promoted', 'disabled')),
    created_by text NOT NULL DEFAULT 'default',
    created_at timestamptz NOT NULL DEFAULT current_timestamp,
    promoted_at timestamptz,
    CHECK (
        (action = 'assign'
            AND target_content_signature IS NOT NULL
            AND target_content_signature <> subject_content_signature)
        OR (action = 'separate' AND target_content_signature IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS software_correction_active_subject_idx
    ON app.software_correction(
        manufacturer_name, system_name, subject_content_signature
    ) WHERE status = 'active';

DROP VIEW IF EXISTS catalog.user_preferred_release;
DROP TABLE IF EXISTS catalog.user_release_score;
DROP TABLE IF EXISTS catalog.user_score_generation;
DROP TABLE IF EXISTS catalog.software_identity_candidate;
DROP TABLE IF EXISTS catalog.software_release_evidence;
DROP TABLE IF EXISTS catalog.software_release;
DROP TABLE IF EXISTS catalog.software;

CREATE TABLE catalog.software (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    system_id bigint NOT NULL
        REFERENCES catalog.system(id) ON DELETE CASCADE,
    preferred_title_id bigint NOT NULL
        REFERENCES catalog.title(id) ON DELETE RESTRICT,
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    identity_basis text NOT NULL CHECK (identity_basis IN (
        'recovered_legacy', 'parent_clone', 'manual', 'title_fallback'
    )),
    source_snapshot_key text,
    source_software_id bigint,
    source_group_key text,
    needs_review boolean NOT NULL,
    CHECK (
        (identity_basis = 'recovered_legacy'
            AND source_snapshot_key IS NOT NULL
            AND source_software_id IS NOT NULL
            AND source_group_key IS NULL
            AND NOT needs_review)
        OR
        (identity_basis = 'parent_clone'
            AND source_snapshot_key IS NOT NULL
            AND source_software_id IS NULL
            AND source_group_key IS NOT NULL
            AND NOT needs_review)
        OR
        (identity_basis = 'manual'
            AND source_snapshot_key IS NULL
            AND source_software_id IS NULL
            AND source_group_key IS NOT NULL
            AND NOT needs_review)
        OR
        (identity_basis = 'title_fallback'
            AND source_snapshot_key IS NULL
            AND source_software_id IS NULL
            AND source_group_key IS NULL
            AND needs_review)
    )
);

CREATE UNIQUE INDEX software_recovered_source_idx
    ON catalog.software(system_id, source_snapshot_key, source_software_id)
    WHERE identity_basis = 'recovered_legacy';
CREATE UNIQUE INDEX software_fallback_title_idx
    ON catalog.software(preferred_title_id)
    WHERE identity_basis = 'title_fallback';
CREATE UNIQUE INDEX software_parent_clone_source_idx
    ON catalog.software(system_id, source_snapshot_key, source_group_key)
    WHERE identity_basis = 'parent_clone';
CREATE UNIQUE INDEX software_manual_key_idx
    ON catalog.software(system_id, source_group_key)
    WHERE identity_basis = 'manual';

CREATE TABLE catalog.software_release (
    release_id bigint PRIMARY KEY
        REFERENCES catalog.release(id) ON DELETE CASCADE,
    software_id bigint NOT NULL
        REFERENCES catalog.software(id) ON DELETE CASCADE,
    assignment_basis text NOT NULL CHECK (assignment_basis IN (
        'exact_sha1', 'parent_clone', 'anchored_title',
        'translation_original_title', 'manual_override',
        'manual_correction', 'title_fallback'
    )),
    evidence_match_count integer NOT NULL
        CHECK (evidence_match_count >= 0),
    needs_review boolean NOT NULL,
    UNIQUE (software_id, release_id),
    CHECK (
        (assignment_basis = 'exact_sha1'
            AND evidence_match_count > 0 AND NOT needs_review)
        OR
        (assignment_basis = 'parent_clone'
            AND evidence_match_count > 0 AND NOT needs_review)
        OR
        (assignment_basis = 'anchored_title'
            AND evidence_match_count > 0 AND needs_review)
        OR
        (assignment_basis = 'translation_original_title'
            AND evidence_match_count > 0 AND needs_review)
        OR
        (assignment_basis = 'manual_override'
            AND evidence_match_count > 0 AND NOT needs_review)
        OR
        (assignment_basis = 'manual_correction'
            AND evidence_match_count > 0 AND NOT needs_review)
        OR
        (assignment_basis = 'title_fallback'
            AND evidence_match_count = 0 AND needs_review)
    )
);

CREATE TABLE catalog.software_release_evidence (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    software_id bigint NOT NULL,
    release_id bigint NOT NULL,
    evidence_type text NOT NULL CHECK (evidence_type IN (
        'exact_legacy_sha1', 'parent_clone_sha1',
        'translation_member_title', 'anchored_title', 'manual_override',
        'manual_content_correction'
    )),
    current_file_id bigint
        REFERENCES derived.file(id) ON DELETE RESTRICT,
    source_snapshot_key text,
    source_record_key text NOT NULL CHECK (btrim(source_record_key) <> ''),
    sha1_hex text CHECK (sha1_hex ~ '^[0-9a-f]{40}$'),
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
    UNIQUE NULLS NOT DISTINCT (
        release_id, evidence_type, current_file_id,
        source_snapshot_key, source_record_key
    ),
    FOREIGN KEY (software_id, release_id)
        REFERENCES catalog.software_release(software_id, release_id)
        ON DELETE CASCADE
);

CREATE TABLE catalog.software_identity_candidate (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_type text NOT NULL CHECK (candidate_type IN (
        'parent_clone_conflict', 'parent_clone_ambiguous_release',
        'reviewed_external_match', 'reviewed_external_rejection'
    )),
    review_status text NOT NULL CHECK (review_status IN (
        'pending', 'accepted', 'rejected'
    )),
    system_id bigint REFERENCES catalog.system(id) ON DELETE CASCADE,
    source_snapshot_key text NOT NULL,
    source_record_key text NOT NULL CHECK (btrim(source_record_key) <> ''),
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
    UNIQUE (candidate_type, source_snapshot_key, source_record_key)
);
