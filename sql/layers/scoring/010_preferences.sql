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
    system_manufacturer text,
    system_name text,
    CONSTRAINT user_preference_match_operator_check
        CHECK (match_operator IN ('equals', 'latest', 'present')),
    CONSTRAINT user_preference_operator_value_check CHECK (
        (match_operator = 'equals' AND nullif(btrim(fact_value), '') IS NOT NULL)
        OR (match_operator IN ('latest', 'present') AND fact_value IS NULL)
    ),
    CONSTRAINT user_preference_system_scope_check CHECK (
        (system_manufacturer IS NULL AND system_name IS NULL)
        OR (
            nullif(btrim(system_manufacturer), '') IS NOT NULL
            AND nullif(btrim(system_name), '') IS NOT NULL
        )
    ),
    UNIQUE NULLS NOT DISTINCT (
        user_id, fact_key, match_operator, fact_value,
        system_manufacturer, system_name
    )
);

-- Existing databases predate system-scoped preferences. Keep the durable
-- rows, widen their uniqueness key, and treat their null scope as global.
ALTER TABLE app.user_preference
    ADD COLUMN IF NOT EXISTS system_manufacturer text,
    ADD COLUMN IF NOT EXISTS system_name text;

-- Existing databases predate the presence operator. Recreate these checks by
-- name so durable preference rows can be migrated without rebuilding app.
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_match_operator_check;
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_check;
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_operator_value_check;
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_system_scope_check;
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_user_id_fact_key_match_operator_fact_value_key;
ALTER TABLE app.user_preference
    DROP CONSTRAINT IF EXISTS user_preference_rule_scope_key;
ALTER TABLE app.user_preference
    ADD CONSTRAINT user_preference_match_operator_check
        CHECK (match_operator IN ('equals', 'latest', 'present')),
    ADD CONSTRAINT user_preference_operator_value_check CHECK (
        (match_operator = 'equals' AND nullif(btrim(fact_value), '') IS NOT NULL)
        OR (match_operator IN ('latest', 'present') AND fact_value IS NULL)
    ),
    ADD CONSTRAINT user_preference_system_scope_check CHECK (
        (system_manufacturer IS NULL AND system_name IS NULL)
        OR (
            nullif(btrim(system_manufacturer), '') IS NOT NULL
            AND nullif(btrim(system_name), '') IS NOT NULL
        )
    ),
    ADD CONSTRAINT user_preference_rule_scope_key UNIQUE NULLS NOT DISTINCT (
        user_id, fact_key, match_operator, fact_value,
        system_manufacturer, system_name
    );

INSERT INTO app.app_user (username)
VALUES ('default')
ON CONFLICT (username) DO NOTHING;

-- Readiness is a ranking tier, not a huge negative preference score.
-- Remove only unchanged seeds; explicit user customizations remain durable.
DELETE FROM app.user_preference p USING app.app_user u
WHERE p.user_id=u.id AND u.username='default'
  AND p.system_manufacturer='Various' AND p.system_name='Arcade'
  AND p.match_operator='equals'
  AND ((p.fact_key='install_status' AND p.fact_value='incomplete' AND p.score=-10000
        AND p.description='Demote incomplete arcade installations')
    OR (p.fact_key='emulation_status' AND p.fact_value='preliminary' AND p.score=-5000
        AND p.description='Demote unsupported arcade machines'));

INSERT INTO app.user_preference (
    user_id, fact_key, match_operator, fact_value, score, description,
    system_manufacturer, system_name
)
SELECT u.id, seed.fact_key, seed.match_operator, seed.fact_value,
    seed.score, seed.description, seed.system_manufacturer, seed.system_name
FROM app.app_user u
CROSS JOIN (
    VALUES
        ('emulator', 'equals', 'FBNeo', 200, 'Prefer FBNeo arcade packages', 'Various', 'Arcade'),
        ('language', 'equals', 'en', 40, 'Prefer explicit English releases', NULL, NULL),
        ('region', 'equals', 'US', 100, 'Prefer US releases', NULL, NULL),
        ('release_iteration', 'latest', NULL, 20, 'Prefer the latest explicit version or revision within software', NULL, NULL),
        ('dump_status', 'equals', 'verified', 30, 'Prefer source-verified dumps', NULL, NULL),
        ('release_status', 'present', NULL, -500, 'Demote non-standard release statuses', NULL, NULL),
        ('demo', 'present', NULL, -500, 'Demote TOSEC demo releases', NULL, NULL),
        ('media_label', 'equals', 'Bonus Disc', -500, 'Demote bonus discs in favor of the main game', NULL, NULL),
        ('dump_status', 'equals', 'alternate', -50, 'Demote alternate dumps', NULL, NULL),
        ('dump_modification', 'equals', 'hacked', -200, 'Demote hacked releases', NULL, NULL),
        ('dump_modification', 'equals', 'undub', 150, 'Prefer releases with original-language audio', NULL, NULL),
        ('source_collection', 'equals', 'No-Intro', 50, 'Prefer No-Intro over unweighted sources', NULL, NULL),
        ('distribution_channel', 'equals', 'virtual_console', -100, 'Demote later Virtual Console distributions', NULL, NULL),
        ('distribution_channel', 'equals', 'wii_u_virtual_console', -100, 'Demote later Wii U Virtual Console distributions', NULL, NULL),
        ('translation_role', 'equals', 'preferred_language_fallback', 30, 'Prefer a translation when no original matches a preferred locale', NULL, NULL),
        ('translation_role', 'equals', 'redundant', -200, 'Demote translations when an original already matches a preferred locale', NULL, NULL),
        ('translation_role', 'equals', 'nonpreferred', -100, 'Demote translations into a non-preferred language', NULL, NULL),
        ('dump_modification', 'equals', 'cracked', 10, 'Prefer copy-protection-free Atari ST releases', 'Atari', 'ST')
) seed(
    fact_key, match_operator, fact_value, score, description,
    system_manufacturer, system_name
)
WHERE u.username = 'default'
ON CONFLICT ON CONSTRAINT user_preference_rule_scope_key DO NOTHING;

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
