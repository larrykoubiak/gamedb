WITH __SOFTWARE_SCOPE__,
facet_values AS (
    SELECT fact.fact_value, fact.software_id
    FROM catalog.software_fact fact
    JOIN chosen ON chosen.software_id = fact.software_id
    WHERE fact.fact_key = __FACT_KEY__ AND fact.is_selected
    UNION ALL
    SELECT value,chosen.software_id FROM chosen JOIN catalog.exo_entry e USING(entry_key)
    CROSS JOIN LATERAL jsonb_array_elements_text(e.facts -> __FACT_KEY__) AS v(value)
), option_values AS MATERIALIZED (
    SELECT fact_value,count(DISTINCT software_id) AS software_count FROM facet_values
    WHERE (__OPTION_SEARCH__ = '' OR position(lower(__OPTION_SEARCH__) in lower(fact_value)) > 0)
    GROUP BY fact_value
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
