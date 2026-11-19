-- Language patches take precedence even when the source also calls one a hack.
CREATE OR REPLACE FUNCTION catalog.is_rom_hack(modifications text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(modifications && ARRAY['hacked','modified','trained'], false)
       AND NOT coalesce(modifications && ARRAY['translated','undub'], false)
$$;

-- Store exceptions to the existing preferred release. A null replacement
-- means every scored release for that game is a ROM hack.
CREATE MATERIALIZED VIEW IF NOT EXISTS app.user_rom_hack_fallback AS
WITH hacks AS MATERIALIZED (
    SELECT release_id FROM catalog.release_fact WHERE fact_key = 'dump_modification'
    GROUP BY release_id HAVING catalog.is_rom_hack(array_agg(fact_value))
), affected AS MATERIALIZED (
    SELECT p.user_id, p.software_id FROM app.user_preferred_release p
    JOIN hacks ON hacks.release_id = p.release_id
), eligible AS (
    SELECT s.*, count(*) OVER (
        PARTITION BY s.user_id, s.software_id, s.rank_within_software
    ) AS tie_count
    FROM affected JOIN app.user_release_score s USING (user_id, software_id)
    WHERE NOT EXISTS (SELECT 1 FROM hacks WHERE hacks.release_id = s.release_id)
), best AS (
    SELECT DISTINCT ON (user_id, software_id)
        user_id, software_id, release_id, score, breakdown, tie_count
    FROM eligible ORDER BY user_id, software_id, rank_within_software, release_id
)
SELECT affected.user_id, affected.software_id, best.release_id, best.score,
    best.breakdown, best.tie_count
FROM affected LEFT JOIN best USING (user_id, software_id)
WITH NO DATA;

REFRESH MATERIALIZED VIEW app.user_rom_hack_fallback;
CREATE UNIQUE INDEX IF NOT EXISTS rom_hack_fallback_software_idx
    ON app.user_rom_hack_fallback (user_id, software_id);
CREATE UNIQUE INDEX IF NOT EXISTS rom_hack_fallback_release_idx
    ON app.user_rom_hack_fallback (user_id, release_id) WHERE release_id IS NOT NULL;
ANALYZE app.user_rom_hack_fallback;

CREATE OR REPLACE VIEW app.user_preferred_release_without_hacks AS
SELECT p.user_id, p.software_id,
    CASE WHEN f.user_id IS NULL THEN p.release_id ELSE f.release_id END AS release_id,
    CASE WHEN f.user_id IS NULL THEN p.score ELSE f.score END AS score,
    CASE WHEN f.user_id IS NULL THEN p.breakdown ELSE f.breakdown END AS breakdown,
    CASE WHEN f.user_id IS NULL THEN p.top_score_tie_count ELSE f.tie_count END AS top_score_tie_count,
    CASE WHEN f.user_id IS NULL THEN p.tie_broken ELSE f.tie_count > 1 END AS tie_broken
FROM app.user_preferred_release p
LEFT JOIN app.user_rom_hack_fallback f USING (user_id, software_id);

-- In-place fact corrections publish with their fallback choices. Full fact
-- rebuilds recreate the table and scoring installs these triggers afterwards.
CREATE OR REPLACE FUNCTION app.refresh_rom_hack_choices() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    changed boolean := TG_OP = 'TRUNCATE';
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT EXISTS (SELECT 1 FROM old_facts WHERE fact_key = 'dump_modification') INTO changed;
    END IF;
    IF NOT changed AND TG_OP IN ('UPDATE', 'INSERT') THEN
        SELECT EXISTS (SELECT 1 FROM new_facts WHERE fact_key = 'dump_modification') INTO changed;
    END IF;
    IF changed AND to_regclass('app.user_rom_hack_fallback') IS NOT NULL THEN
        REFRESH MATERIALIZED VIEW app.user_rom_hack_fallback;
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE TRIGGER refresh_rom_hacks_insert AFTER INSERT ON catalog.release_fact
REFERENCING NEW TABLE AS new_facts FOR EACH STATEMENT EXECUTE FUNCTION app.refresh_rom_hack_choices();
CREATE OR REPLACE TRIGGER refresh_rom_hacks_update AFTER UPDATE ON catalog.release_fact
REFERENCING OLD TABLE AS old_facts NEW TABLE AS new_facts FOR EACH STATEMENT EXECUTE FUNCTION app.refresh_rom_hack_choices();
CREATE OR REPLACE TRIGGER refresh_rom_hacks_delete AFTER DELETE ON catalog.release_fact
REFERENCING OLD TABLE AS old_facts FOR EACH STATEMENT EXECUTE FUNCTION app.refresh_rom_hack_choices();
CREATE OR REPLACE TRIGGER refresh_rom_hacks_truncate AFTER TRUNCATE ON catalog.release_fact
FOR EACH STATEMENT EXECUTE FUNCTION app.refresh_rom_hack_choices();
