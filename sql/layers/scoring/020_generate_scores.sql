-- Compile enabled preferences into a replaceable per-user release score cache.
DROP VIEW IF EXISTS app.user_preferred_release;
DROP TABLE IF EXISTS app.user_release_score;
DROP TABLE IF EXISTS app.user_score_generation;
DROP VIEW IF EXISTS catalog.user_preferred_release;
DROP TABLE IF EXISTS catalog.user_release_score;
DROP TABLE IF EXISTS catalog.user_score_generation;

CREATE TABLE app.user_score_generation (
    user_id bigint PRIMARY KEY REFERENCES app.app_user(id) ON DELETE CASCADE,
    generated_at timestamptz NOT NULL,
    preference_signature text NOT NULL
);

CREATE TABLE app.user_release_score (
    user_id bigint NOT NULL REFERENCES app.app_user(id) ON DELETE CASCADE,
    software_id bigint NOT NULL REFERENCES catalog.software(id) ON DELETE CASCADE,
    release_id bigint NOT NULL REFERENCES catalog.release(id) ON DELETE CASCADE,
    score bigint NOT NULL,
    rank_within_software bigint NOT NULL CHECK (rank_within_software > 0),
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
relative_candidate AS (
    SELECT
        preference.id AS preference_id,
        preference.user_id,
        membership.software_id,
        fact.release_id,
        preference.fact_key,
        fact.fact_key AS matched_fact_key,
        fact.fact_value AS matched_value,
        preference.score,
        preference.description,
        ARRAY(
            SELECT part[1]::numeric
            FROM regexp_matches(fact.fact_value, '([0-9]+)', 'g') part
        ) AS numeric_parts,
        regexp_replace(lower(fact.fact_value), '[^a-z]+', '', 'g') AS text_parts
    FROM app.user_preference preference
    JOIN catalog.release_fact fact
      ON (
          preference.fact_key = 'release_iteration'
          AND fact.fact_key IN ('version', 'revision')
      ) OR (
          preference.fact_key <> 'release_iteration'
          AND fact.fact_key = preference.fact_key
      )
    JOIN catalog.release release ON release.id = fact.release_id
    JOIN catalog.software_release membership
      ON membership.release_id = release.id
    WHERE preference.enabled
      AND preference.match_operator = 'latest'
),
relative_context AS (
    SELECT candidate.*,
        bool_or(candidate.matched_fact_key = 'version') OVER (
            PARTITION BY candidate.preference_id, candidate.user_id,
                candidate.software_id
        ) AS software_has_version
    FROM relative_candidate candidate
),
relative_eligible AS (
    SELECT *
    FROM relative_context
    WHERE fact_key <> 'release_iteration'
       OR matched_fact_key = CASE WHEN software_has_version
            THEN 'version' ELSE 'revision' END
),
relative_ranked AS (
    SELECT eligible.*,
        dense_rank() OVER (
            PARTITION BY preference_id, user_id, software_id
            ORDER BY
                (cardinality(numeric_parts) > 0) DESC,
                numeric_parts DESC,
                CASE WHEN cardinality(numeric_parts) > 0
                    THEN char_length(text_parts) END ASC NULLS LAST,
                text_parts DESC,
                lower(matched_value) DESC
        ) AS relative_rank
    FROM relative_eligible eligible
),
latest_match AS (
    SELECT DISTINCT
        preference_id,
        user_id,
        release_id,
        fact_key,
        CASE WHEN fact_key = 'release_iteration'
            THEN matched_fact_key || '=' || matched_value
            ELSE matched_value
        END AS matched_value,
        score,
        description
    FROM relative_ranked
    WHERE relative_rank = 1
)
SELECT * FROM exact_match
UNION ALL
SELECT * FROM latest_match;

WITH scored AS (
    SELECT
        user_account.id AS user_id,
        membership.software_id,
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
    JOIN catalog.software_release membership
      ON membership.release_id = release.id
    LEFT JOIN _preference_match matched
      ON matched.user_id = user_account.id
     AND matched.release_id = release.id
    GROUP BY user_account.id,
        membership.software_id, release.id
),
ranked AS (
    SELECT scored.*,
        dense_rank() OVER (
            PARTITION BY user_id, software_id
            ORDER BY score DESC
        ) AS rank_within_software
    FROM scored
)
INSERT INTO app.user_release_score (
    user_id, software_id, release_id, score, rank_within_software, breakdown
)
SELECT user_id, software_id, release_id, score, rank_within_software, breakdown
FROM ranked
ORDER BY user_id, software_id, rank_within_software, release_id;

INSERT INTO app.user_score_generation (
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

CREATE INDEX user_release_score_software_rank_idx
    ON app.user_release_score(
        user_id, software_id, rank_within_software, score DESC, release_id
    );
