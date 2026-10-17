-- Aggregate already-typed derived assertions to catalog release facts.
\set ON_ERROR_STOP on
BEGIN;

DROP VIEW IF EXISTS app.user_preferred_release;
DROP TABLE IF EXISTS app.user_release_score;
DROP TABLE IF EXISTS app.user_score_generation;
DROP VIEW IF EXISTS catalog.user_preferred_release;
DROP TABLE IF EXISTS catalog.user_release_score;
DROP TABLE IF EXISTS catalog.user_score_generation;
DROP TABLE IF EXISTS catalog.software_media;
DROP TABLE IF EXISTS catalog.media;
DROP TABLE IF EXISTS catalog.software_identity_candidate;
DROP TABLE IF EXISTS catalog.software_release_evidence;
DROP TABLE IF EXISTS _software_identity_candidate;
DROP TABLE IF EXISTS _software_release_evidence;
DROP TABLE IF EXISTS catalog.software_release;
DROP TABLE IF EXISTS catalog.software;
DROP TABLE IF EXISTS catalog.title_alias;
DROP TABLE IF EXISTS catalog.title_content_match;
DROP TABLE IF EXISTS _title_content_match;
DROP TABLE IF EXISTS catalog.release_content_signature;
DROP TABLE IF EXISTS catalog.package_content_signature;
DROP TABLE IF EXISTS catalog.release_fact_evidence;
DROP TABLE IF EXISTS _release_fact_evidence;
DROP TABLE IF EXISTS catalog.release_fact;

CREATE TABLE catalog.release_fact (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id bigint NOT NULL REFERENCES catalog.release(id) ON DELETE CASCADE,
    fact_key text NOT NULL CHECK (btrim(fact_key) <> ''),
    fact_value text NOT NULL CHECK (btrim(fact_value) <> ''),
    origin text NOT NULL CHECK (origin IN ('source_tag', 'catalog')),
    confidence text NOT NULL CHECK (confidence IN ('explicit', 'computed')),
    UNIQUE (release_id, fact_key, fact_value, origin)
);

CREATE TEMP TABLE _release_fact_evidence (
    release_fact_id bigint NOT NULL,
    release_package_id bigint NOT NULL,
    source_assertion_id bigint NOT NULL,
    PRIMARY KEY (release_fact_id, release_package_id, source_assertion_id)
);
