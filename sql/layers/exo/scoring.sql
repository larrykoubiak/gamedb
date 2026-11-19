-- The same durable user preferences apply to source editions and DAT releases.
INSERT INTO app.user_preference(user_id,fact_key,match_operator,fact_value,score,description,system_manufacturer,system_name)
SELECT u.id,'source_collection','equals','eXo',75,rule.description,rule.manufacturer,rule.system_name
FROM app.app_user u CROSS JOIN (VALUES
    ('Prefer eXo curated editions',NULL::text,NULL::text),
    ('Prefer eXo editions on IBM PC Compatibles','IBM','PC Compatibles')
) rule(description,manufacturer,system_name) WHERE u.username='default'
ON CONFLICT ON CONSTRAINT user_preference_rule_scope_key DO NOTHING;

CREATE TABLE IF NOT EXISTS app.exo_edition_score (
    user_id bigint NOT NULL, edition_key text NOT NULL, score bigint NOT NULL, breakdown jsonb NOT NULL,
    PRIMARY KEY (user_id,edition_key)
);
CREATE TABLE IF NOT EXISTS app.exo_browse_choice (
    user_id bigint NOT NULL, scope_id bigint NOT NULL, software_id bigint NOT NULL, hide_mods boolean NOT NULL,
    edition_key text NOT NULL, entry_key text NOT NULL, score bigint NOT NULL, breakdown jsonb NOT NULL,
    is_mod boolean NOT NULL, tie_count integer NOT NULL,
    PRIMARY KEY (user_id,scope_id,software_id,hide_mods)
);
CREATE TABLE IF NOT EXISTS app.exo_score_generation (
    user_id bigint PRIMARY KEY, signature text NOT NULL
);

CREATE OR REPLACE FUNCTION app.refresh_exo_scores() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('gamedb:exo:catalog'));
    DELETE FROM app.exo_browse_choice;
    DELETE FROM app.exo_edition_score;
    DELETE FROM app.exo_score_generation;
    WITH claims AS MATERIALIZED (
        SELECT DISTINCT e.edition_key,e.system_id,claim.key,claim.value
        FROM catalog.exo_edition e JOIN catalog.exo_entry g USING(entry_key)
        CROSS JOIN LATERAL (VALUES
            ('source_collection','eXo'),
            ('source_collection',CASE g.source_list WHEN 'MS-DOS' THEN 'eXoDOS' WHEN 'Windows 9x' THEN 'eXoWin9x'
                                   ELSE 'eXoScummVM' END),
            ('dump_modification',CASE WHEN e.is_mod THEN 'hacked' END),
            ('release_status',CASE WHEN lower(g.fields->>'ReleaseType') IN ('unreleased','prototype','beta')
                                   THEN lower(g.fields->>'ReleaseType') END),
            ('demo',CASE WHEN lower(g.fields->>'ReleaseType')='demo' OR e.label ~* '\(demo\)' THEN 'demo' END),
            ('version',nullif(g.fields->>'Version','')),
            ('region',CASE g.fields->>'Region' WHEN 'North America' THEN 'US' WHEN 'United States' THEN 'US'
                WHEN 'Japan' THEN 'JP' WHEN 'Europe' THEN 'EU' WHEN 'Germany' THEN 'DE'
                WHEN 'Spain' THEN 'ES' WHEN 'France' THEN 'FR' WHEN 'World' THEN 'World' ELSE g.fields->>'Region' END),
            ('language',CASE lower(g.fields->>'Language') WHEN 'english' THEN 'en' ELSE g.fields->>'Language' END)
        ) claim(key,value) WHERE claim.value IS NOT NULL
    ), reasons AS (
        SELECT DISTINCT ON (p.user_id,c.edition_key,p.id) p.user_id,c.edition_key,p.id,p.score,
               p.description,p.fact_key,p.match_operator,c.value
        FROM claims c JOIN app.user_preference p ON p.enabled AND p.fact_key=c.key
        LEFT JOIN catalog.system s ON s.id=c.system_id
        WHERE (p.match_operator='present' OR (p.match_operator='equals' AND p.fact_value=c.value))
          AND (p.system_name IS NULL OR (p.system_name,p.system_manufacturer)=(s.system_name,s.manufacturer_name))
        ORDER BY p.user_id,c.edition_key,p.id,c.value
    )
    INSERT INTO app.exo_edition_score
    SELECT u.id,e.edition_key,coalesce(sum(r.score),0),coalesce(jsonb_agg(jsonb_build_object(
           'fact_key',r.fact_key,'matched_value',r.value,'match_operator',r.match_operator,
           'score',r.score,'description',r.description) ORDER BY r.id) FILTER (WHERE r.id IS NOT NULL),'[]'::jsonb)
    FROM app.app_user u CROSS JOIN catalog.exo_edition e
    LEFT JOIN reasons r ON (r.user_id,r.edition_key)=(u.id,e.edition_key)
    GROUP BY u.id,e.edition_key;

    WITH candidates AS (
        SELECT score.user_id,b.scope_id,b.software_id,policy.hide_mods,e.edition_key,e.entry_key,score.score,
               score.breakdown,e.is_mod,
               count(*) OVER (PARTITION BY score.user_id,b.scope_id,b.software_id,policy.hide_mods,score.score) AS tie_count,
               row_number() OVER (PARTITION BY score.user_id,b.scope_id,b.software_id,policy.hide_mods
                   ORDER BY score.score DESC,e.is_mod,(g.source_list='ScummVM SVN'),
                            (e.entry_key=b.entry_key) DESC,(e.selection<>''),lower(e.label),e.edition_key) AS position
        FROM catalog.exo_browse b JOIN catalog.exo_edition e USING(work_key)
        JOIN catalog.exo_entry g ON g.entry_key=e.entry_key
        JOIN app.exo_edition_score score USING(edition_key)
        LEFT JOIN catalog.exo_shelf shelf ON shelf.id=b.scope_id
        CROSS JOIN (VALUES(false),(true)) policy(hide_mods)
        WHERE (NOT policy.hide_mods OR NOT e.is_mod) AND (
            (shelf.id IS NULL AND b.system_id IS NOT DISTINCT FROM e.system_id
                              AND (e.system_id IS NOT NULL OR b.system_name=e.environment))
            OR (shelf.name='MS-DOS' AND (g.source_list='MS-DOS' OR e.environment='MS-DOS'))
            OR (shelf.name='ScummVM' AND g.source_list IN ('ScummVM','ScummVM SVN'))
            OR (shelf.name='Windows 9x' AND g.source_list='Windows 9x'))
    )
    INSERT INTO app.exo_browse_choice
    SELECT user_id,scope_id,software_id,hide_mods,edition_key,entry_key,score,breakdown,is_mod,tie_count
    FROM candidates WHERE position=1;

    INSERT INTO app.exo_score_generation
    SELECT user_id,md5(string_agg(md5(concat_ws('|',edition_key,score::text,breakdown::text)),''
        ORDER BY edition_key)) FROM app.exo_edition_score GROUP BY user_id;
    ANALYZE app.exo_browse_choice;
    ANALYZE app.exo_edition_score;
END;
$$;
