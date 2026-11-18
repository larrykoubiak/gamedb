-- The scoring transaction publishes the winners and their tie counts together.
-- This file can also materialize existing scores without regenerating them.
CREATE MATERIALIZED VIEW IF NOT EXISTS app.user_preferred_release_cache AS
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
SELECT user_id, software_id, release_id, score, breakdown, top_score_tie_count,
    (top_score_tie_count > 1) AS tie_broken
FROM top_ranked
WHERE tie_break_order = 1
WITH NO DATA;

REFRESH MATERIALIZED VIEW app.user_preferred_release_cache;
CREATE UNIQUE INDEX IF NOT EXISTS preferred_release_software_idx
    ON app.user_preferred_release_cache (user_id, software_id);
CREATE UNIQUE INDEX IF NOT EXISTS preferred_release_release_idx
    ON app.user_preferred_release_cache (user_id, release_id);
ANALYZE app.user_preferred_release_cache;

CREATE OR REPLACE VIEW app.user_preferred_release AS
SELECT user_id, software_id, release_id, score, breakdown, top_score_tie_count, tie_broken
FROM app.user_preferred_release_cache;
