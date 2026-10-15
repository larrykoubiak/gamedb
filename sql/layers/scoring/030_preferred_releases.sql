-- Expose one convenient default per user/title without hiding unresolved ties,
-- validate the scoring layer, and commit the transaction opened by
-- 010_preferences.sql.
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
    FROM app.app_user
    CROSS JOIN (
        SELECT title.id
        FROM catalog.title title
        WHERE NOT EXISTS (
            SELECT 1 FROM catalog.title_alias alias
            WHERE alias.alias_title_id = title.id
        )
    ) effective_title;
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
    'Disposable per-user release scores, ranks within resolved title aliases and explanations.';
COMMENT ON VIEW catalog.user_preferred_release IS
    'One highest-scoring release per user/title, with deterministic tie metadata.';

ANALYZE app.app_user;
ANALYZE app.user_preference;
ANALYZE catalog.user_score_generation;
ANALYZE catalog.user_release_score;

COMMIT;
