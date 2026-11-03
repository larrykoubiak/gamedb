WITH __SOFTWARE_SCOPE__,
option_values AS MATERIALIZED (
    SELECT fact.fact_value, count(DISTINCT fact.software_id) AS software_count
    FROM catalog.software_fact fact
    JOIN chosen ON chosen.software_id = fact.software_id
    WHERE fact.fact_key = __FACT_KEY__ AND fact.is_selected
      AND (__OPTION_SEARCH__ = ''
           OR position(lower(__OPTION_SEARCH__) in lower(fact.fact_value)) > 0)
    GROUP BY fact.fact_value
), limited AS (
    SELECT * FROM option_values
    ORDER BY lower(fact_value), fact_value
    LIMIT 100
)
SELECT jsonb_build_object(
    'total', (SELECT count(*) FROM option_values),
    'items', coalesce((SELECT jsonb_agg(jsonb_build_object(
        'value', fact_value, 'count', software_count
    ) ORDER BY lower(fact_value), fact_value) FROM limited), '[]'::jsonb)
);
