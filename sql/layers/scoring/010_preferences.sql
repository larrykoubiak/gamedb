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
    match_operator text NOT NULL,
    fact_value text,
    score integer NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    description text NOT NULL CHECK (btrim(description) <> ''),
    CONSTRAINT user_preference_match_operator_check
        CHECK (match_operator IN ('equals', 'latest', 'present')),
    CONSTRAINT user_preference_operator_value_check CHECK (
        (match_operator = 'equals' AND nullif(btrim(fact_value), '') IS NOT NULL)
        OR (match_operator IN ('latest', 'present') AND fact_value IS NULL)
    ),
    UNIQUE NULLS NOT DISTINCT (
        user_id, fact_key, match_operator, fact_value
    )
);

-- Existing databases predate the presence operator. Recreate these checks by
-- name so durable preference rows can be migrated without rebuilding app.
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_match_operator_check;
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_check;
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_operator_value_check;
ALTER TABLE app.user_preference
    ADD CONSTRAINT user_preference_match_operator_check
        CHECK (match_operator IN ('equals', 'latest', 'present')),
    ADD CONSTRAINT user_preference_operator_value_check CHECK (
        (match_operator = 'equals' AND nullif(btrim(fact_value), '') IS NOT NULL)
        OR (match_operator IN ('latest', 'present') AND fact_value IS NULL)
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
        ('release_iteration', 'latest', NULL, 20, 'Prefer the latest explicit version or revision within software'),
        ('dump_status', 'equals', 'verified', 30, 'Prefer source-verified dumps'),
        ('release_status', 'present', NULL, -500, 'Demote non-standard release statuses'),
        ('demo', 'present', NULL, -500, 'Demote TOSEC demo releases'),
        ('dump_status', 'equals', 'alternate', -50, 'Demote alternate dumps'),
        ('dump_modification', 'equals', 'hacked', -200, 'Demote hacked releases'),
        ('source_collection', 'equals', 'No-Intro', 50, 'Prefer No-Intro over unweighted sources')
) seed(fact_key, match_operator, fact_value, score, description)
WHERE u.username = 'default'
ON CONFLICT (user_id, fact_key, match_operator, fact_value) DO NOTHING;

-- Supersede only the untouched beta seed. A customized beta preference is a
-- deliberate additional rule and remains durable.
DELETE FROM app.user_preference preference
USING app.app_user user_account
WHERE preference.user_id = user_account.id
  AND user_account.username = 'default'
  AND preference.fact_key = 'release_status'
  AND preference.match_operator = 'equals'
  AND preference.fact_value = 'beta'
  AND preference.score = -100
  AND preference.description = 'Demote beta releases';

-- Migrate only the original seed wording; preserve genuinely customized
-- descriptions on durable user preferences.
UPDATE app.user_preference
SET description = 'Prefer the latest explicit version or revision within software'
WHERE fact_key = 'release_iteration'
  AND match_operator = 'latest'
  AND description = 'Prefer the latest explicit version or revision within a title';
