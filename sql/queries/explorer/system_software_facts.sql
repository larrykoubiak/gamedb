WITH fact_rows AS (
    SELECT
        fact.software_id,
        fact.fact_key,
        fact.fact_value,
        fact.value_rank,
        fact.value_count,
        fact.matched_content_count,
        fact.source_record_count,
        fact.source_provider,
        fact.source_revision,
        coalesce(evidence.databases, '[]'::jsonb) AS source_databases,
        coalesce(evidence.matches, '[]'::jsonb) AS matches
    FROM catalog.software_fact fact
    JOIN catalog.software software ON software.id = fact.software_id
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(DISTINCT source_database ORDER BY source_database) AS databases,
            jsonb_agg(DISTINCT jsonb_build_object(
                'method', match_method,
                'databaseId', match_details -> 'database_id',
                'basis', match_details -> 'resolution_basis'
            )) AS matches
        FROM (
            SELECT DISTINCT source_database, match_method, match_details
            FROM catalog.software_fact_evidence
            WHERE software_fact_id = fact.id
        ) sources
    ) evidence ON true
    WHERE software.system_id = __SYSTEM_ID__
), fact_groups AS (
    SELECT
        software_id,
        fact_key,
        jsonb_agg(
            jsonb_build_object(
                'value', fact_value,
                'rank', value_rank,
                'candidateCount', value_count,
                'matchedContentCount', matched_content_count,
                'sourceRecordCount', source_record_count,
                'sourceProvider', source_provider,
                'sourceRevision', source_revision,
                'sourceDatabases', source_databases,
                'matches', matches
            ) ORDER BY value_rank, lower(fact_value), fact_value
        ) AS values
    FROM fact_rows
    GROUP BY software_id, fact_key
), software_groups AS (
    SELECT
        software_id,
        jsonb_agg(
            jsonb_build_object(
                'key', fact_key,
                'values', values
            ) ORDER BY
                CASE fact_key
                    WHEN 'developer' THEN 1
                    WHEN 'publisher' THEN 2
                    WHEN 'genre' THEN 3
                    WHEN 'franchise' THEN 4
                    WHEN 'player_count' THEN 5
                    WHEN 'enhancement_hardware' THEN 6
                    WHEN 'rumble' THEN 7
                    WHEN 'analog' THEN 8
                    WHEN 'origin' THEN 9
                    WHEN 'tags' THEN 10
                    WHEN 'description' THEN 11
                    ELSE 99
                END,
                fact_key
        ) AS facts
    FROM fact_groups
    GROUP BY software_id
)
SELECT coalesce(
    jsonb_object_agg(software_id::text, facts ORDER BY software_id),
    '{}'::jsonb
)
FROM software_groups;
