-- Expose one convenient default per user/software without hiding unresolved ties,
-- validate the scoring layer, and commit the transaction opened by
-- 010_preferences.sql.
-- release_id is only a deterministic fallback when several releases share the
-- best readiness tier and score; consumers can use top_score_tie_count to surface that ambiguity.
CREATE VIEW app.user_preferred_release AS
WITH top_ranked AS (
    SELECT score.*,
        count(*) OVER (
            PARTITION BY score.user_id, score.software_id
        ) AS top_score_tie_count,
        row_number() OVER (
            PARTITION BY score.user_id, score.software_id
            ORDER BY score.release_id
        ) AS tie_break_order
    FROM app.user_release_score score
    WHERE score.rank_within_software = 1
)
SELECT
    user_id,
    software_id,
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
    SELECT count(*) INTO actual_count FROM app.user_release_score;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog user-release score count %, expected %',
            actual_count, expected_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM (
        SELECT user_id, software_id
        FROM app.user_release_score
        GROUP BY user_id, software_id
        HAVING min(rank_within_software) <> 1
    ) invalid_ranks;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% user/software score groups do not start at rank 1',
            actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM app.user_preference preference
    LEFT JOIN catalog.system system
      ON system.manufacturer_name = preference.system_manufacturer
     AND system.system_name = preference.system_name
    WHERE preference.enabled
      AND preference.system_manufacturer IS NOT NULL
      AND system.id IS NULL;
    IF actual_count <> 0 THEN
        RAISE EXCEPTION '% enabled score preferences have an unknown system scope',
            actual_count;
    END IF;

    SELECT count(*) INTO expected_count
    FROM app.app_user
    CROSS JOIN catalog.software;
    SELECT count(*) INTO actual_count FROM app.user_preferred_release;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'catalog preferred-release count %, expected %',
            actual_count, expected_count;
    END IF;
END;
$$;

COMMENT ON TABLE app.app_user IS
    'Durable local users whose preferences survive catalog rebuilds.';
COMMENT ON TABLE app.user_preference IS
    'Durable global or exact-system additive fact preferences and supported relative scoring rules.';
COMMENT ON TABLE app.user_score_generation IS
    'Timestamp and enabled-preference signature for the active score cache.';
COMMENT ON TABLE app.user_release_score IS
    'Disposable per-user release scores, ranks within software identities and explanations.';
COMMENT ON VIEW app.user_preferred_release IS
    'One preferred release per user/software; arcade readiness precedes preference score, with deterministic tie metadata.';

ANALYZE app.app_user;
ANALYZE app.user_preference;
ANALYZE app.user_score_generation;
ANALYZE app.user_release_score;

COMMIT;
