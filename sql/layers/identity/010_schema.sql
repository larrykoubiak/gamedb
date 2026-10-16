-- Rebuild exact-content signatures and non-destructive title aliases from the
-- existing catalog files and facts. Score caches depend on these aliases.
\set ON_ERROR_STOP on
BEGIN;

DROP VIEW IF EXISTS catalog.user_preferred_release;
DROP TABLE IF EXISTS catalog.user_release_score;
DROP TABLE IF EXISTS catalog.user_score_generation;
DROP TABLE IF EXISTS catalog.software_identity_candidate;
DROP TABLE IF EXISTS catalog.software_release_evidence;
DROP TABLE IF EXISTS catalog.software_release;
DROP TABLE IF EXISTS catalog.software;
DROP TABLE IF EXISTS catalog.title_alias;
DROP TABLE IF EXISTS catalog.title_content_match;
DROP TABLE IF EXISTS catalog.release_content_signature;
DROP TABLE IF EXISTS catalog.package_content_signature;

CREATE TABLE catalog.package_content_signature (
    package_id bigint PRIMARY KEY
        REFERENCES derived.package(id) ON DELETE CASCADE,
    release_id bigint NOT NULL
        REFERENCES catalog.release(id) ON DELETE CASCADE,
    rom_count integer NOT NULL CHECK (rom_count > 0),
    sha1_set_digest text NOT NULL CHECK (sha1_set_digest ~ '^[0-9a-f]{32}$')
);

CREATE TABLE catalog.release_content_signature (
    release_id bigint PRIMARY KEY
        REFERENCES catalog.release(id) ON DELETE CASCADE,
    package_count integer NOT NULL CHECK (package_count > 0),
    rom_count integer NOT NULL CHECK (rom_count > 0),
    sha1_set_digest text NOT NULL CHECK (sha1_set_digest ~ '^[0-9a-f]{32}$')
);

CREATE TABLE catalog.title_alias (
    alias_title_id bigint PRIMARY KEY
        REFERENCES catalog.title(id) ON DELETE CASCADE,
    preferred_title_id bigint NOT NULL
        REFERENCES catalog.title(id) ON DELETE RESTRICT,
    match_basis text NOT NULL CHECK (match_basis = 'exact_content_component'),
    component_title_count integer NOT NULL CHECK (component_title_count > 1),
    evidence_pair_count integer NOT NULL CHECK (evidence_pair_count > 0),
    CHECK (alias_title_id <> preferred_title_id)
);

CREATE TABLE catalog.title_content_match (
    left_title_id bigint NOT NULL
        REFERENCES catalog.title(id) ON DELETE CASCADE,
    right_title_id bigint NOT NULL
        REFERENCES catalog.title(id) ON DELETE CASCADE,
    left_release_id bigint NOT NULL
        REFERENCES catalog.release(id) ON DELETE CASCADE,
    right_release_id bigint NOT NULL
        REFERENCES catalog.release(id) ON DELETE CASCADE,
    matched_rom_count integer NOT NULL CHECK (matched_rom_count > 0),
    sha1_set_digest text NOT NULL CHECK (sha1_set_digest ~ '^[0-9a-f]{32}$'),
    PRIMARY KEY (left_release_id, right_release_id),
    CHECK (left_title_id < right_title_id),
    CHECK (left_release_id <> right_release_id)
);
