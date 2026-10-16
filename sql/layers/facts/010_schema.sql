-- Aggregate already-typed derived assertions to catalog release facts.
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
    source_assertion_id bigint NOT NULL
        REFERENCES derived.assertion(id) ON DELETE RESTRICT,
    PRIMARY KEY (release_fact_id, release_package_id, source_assertion_id)
);

CREATE VIEW catalog.release_source_attribute AS
SELECT
    rp.release_id,
    rp.id AS release_package_id,
    tag.archive_name_id AS source_archive_name_id,
    tag.record_index AS source_record_index,
    tag.tag_index,
    classification.category,
    classification.classification_status,
    tag.raw_value,
    classification.identifier,
    classification.value,
    classification.details,
    classification.rule
FROM catalog.release_package rp
JOIN derived.tag tag
  ON tag.archive_name_id = rp.source_archive_name_id
 AND tag.record_index = rp.source_record_index
JOIN derived.tag_classification classification
  ON classification.archive_name_id = tag.archive_name_id
 AND classification.record_index = tag.record_index
 AND classification.tag_index = tag.tag_index;
