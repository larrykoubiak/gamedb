-- Create durable personal preferences and compile them into a disposable
-- per-release score cache. Run after 003_catalog.sql.
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
        ('language', 'equals', 'en', 100, 'Prefer explicit English releases'),
        ('release_date', 'latest', NULL, 20, 'Prefer the latest known release date within a title'),
        ('dump_status', 'equals', 'verified', 30, 'Prefer source-verified dumps'),
        ('dump_modification', 'equals', 'hacked', -200, 'Demote hacked releases'),
        ('source_collection', 'equals', 'No-Intro', 50, 'Prefer No-Intro over unweighted sources')
) seed(fact_key, match_operator, fact_value, score, description)
WHERE u.username = 'default'
ON CONFLICT (user_id, fact_key, match_operator, fact_value) DO NOTHING;

DROP VIEW IF EXISTS catalog.user_preferred_release;
DROP TABLE IF EXISTS catalog.user_release_score;
DROP TABLE IF EXISTS catalog.user_score_generation;

CREATE TABLE catalog.user_score_generation (
    user_id bigint PRIMARY KEY REFERENCES app.app_user(id) ON DELETE CASCADE,
    generated_at timestamptz NOT NULL,
    preference_signature text NOT NULL
);

CREATE TABLE catalog.user_release_score (
    user_id bigint NOT NULL REFERENCES app.app_user(id) ON DELETE CASCADE,
    title_id bigint NOT NULL REFERENCES catalog.title(id) ON DELETE CASCADE,
    release_id bigint NOT NULL REFERENCES catalog.release(id) ON DELETE CASCADE,
    score bigint NOT NULL,
    rank_within_title bigint NOT NULL CHECK (rank_within_title > 0),
    breakdown jsonb NOT NULL CHECK (jsonb_typeof(breakdown) = 'array'),
    PRIMARY KEY (user_id, release_id)
);

CREATE TEMP TABLE _preference_match ON COMMIT DROP AS
WITH exact_match AS (
    SELECT DISTINCT
        preference.id AS preference_id,
        preference.user_id,
        fact.release_id,
        preference.fact_key,
        fact.fact_value AS matched_value,
        preference.score,
        preference.description
    FROM app.user_preference preference
    JOIN catalog.release_fact fact
      ON fact.fact_key = preference.fact_key
     AND fact.fact_value = preference.fact_value
    WHERE preference.enabled
      AND preference.match_operator = 'equals'
),
dated_release AS (
    SELECT release.title_id, fact.release_id,
        max(fact.fact_value) AS release_date
    FROM catalog.release_fact fact
    JOIN catalog.release release ON release.id = fact.release_id
    WHERE fact.fact_key = 'release_date'
      AND fact.fact_value ~ '^[0-9]{4}(-[0-9]{2})?(-[0-9]{2})?$'
    GROUP BY release.title_id, fact.release_id
),
latest_title_date AS (
    SELECT title_id, max(release_date) AS release_date
    FROM dated_release
    GROUP BY title_id
),
latest_match AS (
    SELECT
        preference.id AS preference_id,
        preference.user_id,
        dated.release_id,
        preference.fact_key,
        dated.release_date AS matched_value,
        preference.score,
        preference.description
    FROM app.user_preference preference
    JOIN dated_release dated ON true
    JOIN latest_title_date latest
      ON latest.title_id = dated.title_id
     AND latest.release_date = dated.release_date
    WHERE preference.enabled
      AND preference.match_operator = 'latest'
      AND preference.fact_key = 'release_date'
)
SELECT * FROM exact_match
UNION ALL
SELECT * FROM latest_match;

WITH scored AS (
    SELECT
        user_account.id AS user_id,
        release.title_id,
        release.id AS release_id,
        coalesce(sum(matched.score), 0) AS score,
        coalesce(
            jsonb_agg(
                jsonb_build_object(
                    'preference_id', matched.preference_id,
                    'fact_key', matched.fact_key,
                    'matched_value', matched.matched_value,
                    'score', matched.score,
                    'description', matched.description
                ) ORDER BY matched.preference_id
            ) FILTER (WHERE matched.preference_id IS NOT NULL),
            '[]'::jsonb
        ) AS breakdown
    FROM app.app_user user_account
    CROSS JOIN catalog.release release
    LEFT JOIN _preference_match matched
      ON matched.user_id = user_account.id
     AND matched.release_id = release.id
    GROUP BY user_account.id, release.title_id, release.id
),
ranked AS (
    SELECT scored.*,
        dense_rank() OVER (
            PARTITION BY user_id, title_id
            ORDER BY score DESC
        ) AS rank_within_title
    FROM scored
)
INSERT INTO catalog.user_release_score (
    user_id, title_id, release_id, score, rank_within_title, breakdown
)
SELECT user_id, title_id, release_id, score, rank_within_title, breakdown
FROM ranked
ORDER BY user_id, title_id, rank_within_title, release_id;

INSERT INTO catalog.user_score_generation (
    user_id, generated_at, preference_signature
)
SELECT user_account.id, transaction_timestamp(),
    md5(coalesce(
        string_agg(
            concat_ws('|', preference.fact_key, preference.match_operator,
                preference.fact_value, preference.score::text),
            E'\n' ORDER BY preference.fact_key, preference.match_operator,
                preference.fact_value, preference.score
        ) FILTER (WHERE preference.enabled),
        ''
    ))
FROM app.app_user user_account
LEFT JOIN app.user_preference preference
  ON preference.user_id = user_account.id
GROUP BY user_account.id;

CREATE INDEX user_release_score_title_rank_idx
    ON catalog.user_release_score(
        user_id, title_id, rank_within_title, score DESC, release_id
    );

-- Return one convenient default per user/title without hiding unresolved ties.
-- release_id is only a deterministic fallback when several releases share the
-- best score; consumers can use top_score_tie_count to surface that ambiguity.
CREATE VIEW catalog.user_preferred_release AS
WITH top_ranked AS (
    SELECT score.*,
        count(*) OVER (
            PARTITION BY score.user_id, score.title_id
        ) AS top_score_tie_count,
        row_number() OVER (
            PARTITION BY score.user_id, score.title_id
            ORDER BY score.release_id
        ) AS tie_break_order
    FROM catalog.user_release_score score
    WHERE score.rank_within_title = 1
)
SELECT
    user_id,
    title_id,
    release_id,
    score,
    breakdown,
    top_score_tie_count,
    (top_score_tie_count > 1) AS tie_broken
FROM top_ranked
WHERE tie_break_order = 1;

DO $$
DECLARE
    expected_count bigint;
    actual_count bigint;
BEGIN
    SELECT count(*) INTO expected_count
    FROM app.app_user CROSS JOIN catalog.release;
    SELECT count(*) INTO actual_count FROM catalog.user_release_score;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog user-release score count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM (
        SELECT user_id, title_id
        FROM catalog.user_release_score
        GROUP BY user_id, title_id
        HAVING min(rank_within_title) <> 1
    ) invalid_ranks;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% user/title score groups do not start at rank 1',
            actual_count;
    END IF;

    SELECT count(*) INTO expected_count
    FROM app.app_user CROSS JOIN catalog.title;
    SELECT count(*) INTO actual_count FROM catalog.user_preferred_release;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog preferred-release count %, expected %',
            actual_count, expected_count;
    END IF;
END;
$$;

COMMENT ON TABLE app.app_user IS
    'Durable local users whose preferences survive catalog rebuilds.';
COMMENT ON TABLE app.user_preference IS
    'Durable additive fact preferences and supported relative scoring rules.';
COMMENT ON TABLE catalog.user_score_generation IS
    'Timestamp and enabled-preference signature for the active score cache.';
COMMENT ON TABLE catalog.user_release_score IS
    'Disposable per-user release scores, title-relative ranks and explanations.';
COMMENT ON VIEW catalog.user_preferred_release IS
    'One highest-scoring release per user/title, with deterministic tie metadata.';

ANALYZE app.app_user;
ANALYZE app.user_preference;
ANALYZE catalog.user_score_generation;
ANALYZE catalog.user_release_score;

COMMIT;
