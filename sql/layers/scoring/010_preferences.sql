-- Create personal preferences and compile them into a disposable per-release
-- score cache. Run after the catalog layer.
\set ON_ERROR_STOP on
BEGIN;

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.app_user (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username text NOT NULL UNIQUE CHECK (btrim(username) <> '')
);

CREATE TABLE IF NOT EXISTS app.user_preference (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES app.app_user(id) ON DELETE CASCADE,
    fact_key text NOT NULL CHECK (btrim(fact_key) <> ''),
    match_operator text NOT NULL CHECK (match_operator IN ('equals', 'latest')),
    fact_value text,
    score integer NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    description text NOT NULL CHECK (btrim(description) <> ''),
    CHECK (
        (match_operator = 'equals' AND nullif(btrim(fact_value), '') IS NOT NULL)
        OR (match_operator = 'latest' AND fact_value IS NULL)
    ),
    UNIQUE NULLS NOT DISTINCT (
        user_id, fact_key, match_operator, fact_value
    )
);

INSERT INTO app.app_user (username)
VALUES ('default')
ON CONFLICT (username) DO NOTHING;

INSERT INTO app.user_preference (
    user_id, fact_key, match_operator, fact_value, score, description
)
SELECT u.id, seed.fact_key, seed.match_operator, seed.fact_value,
    seed.score, seed.description
FROM app.app_user u
CROSS JOIN (
    VALUES
        ('language', 'equals', 'en', 40, 'Prefer explicit English releases'),
        ('region', 'equals', 'US', 100, 'Prefer US releases'),
        ('release_iteration', 'latest', NULL, 20, 'Prefer the latest explicit version or revision within a title'),
        ('dump_status', 'equals', 'verified', 30, 'Prefer source-verified dumps'),
        ('dump_modification', 'equals', 'hacked', -200, 'Demote hacked releases'),
        ('source_collection', 'equals', 'No-Intro', 50, 'Prefer No-Intro over unweighted sources')
) seed(fact_key, match_operator, fact_value, score, description)
WHERE u.username = 'default'
ON CONFLICT (user_id, fact_key, match_operator, fact_value) DO NOTHING;
