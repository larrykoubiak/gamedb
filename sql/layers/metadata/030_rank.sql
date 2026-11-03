-- Source preference is field-local: absent LaunchBox fields fall back to RDB.
-- Scores express preference, not a statistical confidence percentage.
WITH source_scores(source_provider, score) AS (
    VALUES ('launchbox', 100), ('libretro-database', 50)
), scored AS (
    SELECT f.*, s.score,
        max(s.score) OVER (PARTITION BY software_id, fact_key) AS best_score
    FROM catalog.software_fact f
    JOIN source_scores s USING (source_provider)
), ranked AS (
    SELECT scored.*,
        row_number() OVER (PARTITION BY software_id, fact_key
            ORDER BY score DESC, matched_content_count DESC, source_record_count DESC,
                lower(fact_value), fact_value, source_revision) AS rank,
        count(*) OVER (PARTITION BY software_id, fact_key) AS total
    FROM scored
)
UPDATE catalog.software_fact f
SET source_score=r.score, value_rank=r.rank, value_count=r.total,
    is_selected=CASE WHEN r.fact_key='genre' THEN r.score=r.best_score ELSE r.rank=1 END
FROM ranked r WHERE f.id=r.id;
