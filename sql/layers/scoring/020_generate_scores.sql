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
WITH scoped_preference AS (
    SELECT preference.*, system.id AS system_id
    FROM app.user_preference preference
    LEFT JOIN catalog.system system
      ON system.manufacturer_name = preference.system_manufacturer
     AND system.system_name = preference.system_name
    WHERE preference.enabled
      AND (
          preference.system_manufacturer IS NULL
          OR system.id IS NOT NULL
      )
),
locale_preference AS (
    SELECT *
    FROM scoped_preference
    WHERE match_operator = 'equals'
      AND fact_key IN ('language', 'region')
      AND score > 0
),
clean_preferred_locale AS (
    SELECT DISTINCT
        preference.user_id,
        membership.software_id
    FROM locale_preference preference
    JOIN catalog.release_fact locale
      ON locale.fact_key = preference.fact_key
     AND locale.fact_value = preference.fact_value
    JOIN catalog.release release ON release.id = locale.release_id
    JOIN catalog.title title ON title.id = release.title_id
    JOIN catalog.software_release membership
      ON membership.release_id = release.id
    WHERE (preference.system_id IS NULL OR preference.system_id = title.system_id)
      AND NOT EXISTS (
          SELECT 1
          FROM catalog.release_fact modification
          WHERE modification.release_id = release.id
            AND modification.fact_key = 'dump_modification'
      )
),
translation_role AS (
    SELECT DISTINCT
        user_account.id AS user_id,
        membership.software_id,
        translated.release_id,
        CASE
            WHEN clean.user_id IS NOT NULL THEN 'redundant'
            WHEN EXISTS (
                SELECT 1
                FROM locale_preference language_preference
                JOIN catalog.release_fact language
                  ON language.release_id = translated.release_id
                 AND language.fact_key = 'language'
                 AND language.fact_value = language_preference.fact_value
                WHERE language_preference.user_id = user_account.id
                  AND language_preference.fact_key = 'language'
                  AND (
                      language_preference.system_id IS NULL
                      OR language_preference.system_id = title.system_id
                  )
            ) THEN 'preferred_language_fallback'
            ELSE 'nonpreferred'
        END AS role
    FROM app.app_user user_account
    JOIN catalog.release_fact translated
      ON translated.fact_key = 'dump_modification'
     AND translated.fact_value = 'translated'
    JOIN catalog.release release ON release.id = translated.release_id
    JOIN catalog.title title ON title.id = release.title_id
    JOIN catalog.software_release membership
      ON membership.release_id = release.id
    LEFT JOIN clean_preferred_locale clean
      ON clean.user_id = user_account.id
     AND clean.software_id = membership.software_id
),
exact_match AS (
    SELECT DISTINCT
        preference.id AS preference_id,
        preference.user_id,
        fact.release_id,
        preference.fact_key,
        fact.fact_value AS matched_value,
        preference.score,
        preference.description
    FROM scoped_preference preference
    JOIN catalog.release_fact fact
      ON fact.fact_key = preference.fact_key
     AND fact.fact_value = preference.fact_value
    JOIN catalog.release release ON release.id = fact.release_id
    JOIN catalog.title title ON title.id = release.title_id
    WHERE preference.match_operator = 'equals'
      AND (preference.system_id IS NULL OR preference.system_id = title.system_id)
),
contextual_match AS (
    SELECT DISTINCT
        preference.id AS preference_id,
        preference.user_id,
        role.release_id,
        preference.fact_key,
        role.role AS matched_value,
        preference.score,
        preference.description
    FROM scoped_preference preference
    JOIN translation_role role
      ON role.user_id = preference.user_id
     AND role.role = preference.fact_value
    JOIN catalog.release release ON release.id = role.release_id
    JOIN catalog.title title ON title.id = release.title_id
    WHERE preference.match_operator = 'equals'
      AND preference.fact_key = 'translation_role'
      AND (preference.system_id IS NULL OR preference.system_id = title.system_id)
),
presence_match AS (
    SELECT
        preference.id AS preference_id,
        preference.user_id,
        fact.release_id,
        preference.fact_key,
        min(fact.fact_value) AS matched_value,
        preference.score,
        preference.description
    FROM scoped_preference preference
    JOIN catalog.release_fact fact
      ON fact.fact_key = preference.fact_key
    JOIN catalog.release release ON release.id = fact.release_id
    JOIN catalog.title title ON title.id = release.title_id
    WHERE preference.match_operator = 'present'
      AND (preference.system_id IS NULL OR preference.system_id = title.system_id)
    GROUP BY preference.id, preference.user_id, fact.release_id,
        preference.fact_key, preference.score, preference.description
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
    FROM scoped_preference preference
    JOIN catalog.release_fact fact
      ON (
          preference.fact_key = 'release_iteration'
          AND fact.fact_key IN ('version', 'revision')
      ) OR (
          preference.fact_key <> 'release_iteration'
          AND fact.fact_key = preference.fact_key
      )
    JOIN catalog.release release ON release.id = fact.release_id
    JOIN catalog.title title ON title.id = release.title_id
    JOIN catalog.software_release membership
      ON membership.release_id = release.id
    WHERE preference.match_operator = 'latest'
      AND (preference.system_id IS NULL OR preference.system_id = title.system_id)
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
SELECT * FROM contextual_match
UNION ALL
SELECT * FROM presence_match
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
                preference.fact_value, preference.score::text,
                preference.system_manufacturer, preference.system_name),
            E'\n' ORDER BY preference.fact_key, preference.match_operator,
                preference.fact_value, preference.score,
                preference.system_manufacturer, preference.system_name
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
