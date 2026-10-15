-- Rebuild normalized release facts from the existing core catalog. Downstream
-- identity and score caches are invalid until their own layers run again.
\set ON_ERROR_STOP on
BEGIN;

DROP VIEW IF EXISTS catalog.user_preferred_release;
DROP TABLE IF EXISTS catalog.user_release_score;
DROP TABLE IF EXISTS catalog.user_score_generation;
DROP TABLE IF EXISTS catalog.title_alias;
DROP TABLE IF EXISTS catalog.title_content_match;
DROP TABLE IF EXISTS catalog.release_content_signature;
DROP TABLE IF EXISTS catalog.package_content_signature;
DROP VIEW IF EXISTS catalog.release_source_attribute;
DROP TABLE IF EXISTS catalog.release_fact_evidence;
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

CREATE TABLE catalog.release_fact_evidence (
    release_fact_id bigint NOT NULL
        REFERENCES catalog.release_fact(id) ON DELETE CASCADE,
    release_package_id bigint NOT NULL
        REFERENCES catalog.release_package(id) ON DELETE CASCADE,
    source_archive_tag_id bigint NOT NULL
        REFERENCES derived.archive_tag(id) ON DELETE RESTRICT,
    PRIMARY KEY (
        release_fact_id, release_package_id, source_archive_tag_id
    )
);

CREATE VIEW catalog.release_source_attribute AS
SELECT
    rp.release_id,
    rp.id AS release_package_id,
    t.id AS source_archive_tag_id,
    t.tag_index,
    t.category,
    t.classification_status,
    t.raw_value,
    t.identifier,
    t.value,
    t.details,
    t.rule
FROM catalog.release_package rp
JOIN derived.archive_tag t
  ON t.archive_name_record_id = rp.source_archive_name_record_id;
