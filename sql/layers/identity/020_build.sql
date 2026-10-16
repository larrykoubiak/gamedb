-- Reconcile same-system titles using complete package/release content. Hash
-- identity is evaluated before names. A package signature is eligible
-- only when the package belongs to one release; compound archives cannot prove
-- that each named record owns every file in the shared package. The known .pok
-- trainer format is not a playable ROM and is excluded from identity. Every
-- remaining member must have SHA-1 and duplicate hashes remain significant.
-- The self-join used for content components can otherwise select a parallel
-- hash plan larger than the PostgreSQL container's shared-memory allocation.
SET LOCAL max_parallel_workers_per_gather = 0;

WITH package_owner AS (
    SELECT package_id, min(release_id) AS release_id
    FROM catalog.release_package
    GROUP BY package_id
    HAVING count(DISTINCT release_id) = 1
)
INSERT INTO catalog.package_content_signature (
    package_id, release_id, rom_count, sha1_set_digest
)
SELECT
    owner.package_id,
    owner.release_id,
    count(file.id)::integer,
    md5(string_agg(file.sha1_hex, E'\n' ORDER BY file.sha1_hex))
FROM package_owner owner
JOIN catalog.package_file file ON file.package_id = owner.package_id
WHERE lower(file.file_name) !~ '\.pok$'
GROUP BY owner.package_id, owner.release_id
HAVING bool_and(file.sha1_hex IS NOT NULL)
ORDER BY owner.package_id;

INSERT INTO catalog.release_content_signature (
    release_id, package_count, rom_count, sha1_set_digest
)
SELECT
    release.id,
    count(signature.package_id)::integer,
    sum(signature.rom_count)::integer,
    md5(string_agg(
        signature.sha1_set_digest,
        E'\n' ORDER BY signature.sha1_set_digest
    ))
FROM catalog.release release
JOIN catalog.release_package release_package
  ON release_package.release_id = release.id
LEFT JOIN catalog.package_content_signature signature
  ON signature.package_id = release_package.package_id
GROUP BY release.id
HAVING count(signature.package_id) = count(release_package.package_id)
ORDER BY release.id;

-- Reconciliation immediately below joins release fingerprints by their
-- complete signature. Build and analyze that access path before planning.
CREATE INDEX release_content_signature_match_idx
    ON catalog.release_content_signature(
        package_count, rom_count, sha1_set_digest
    );
ANALYZE catalog.release_content_signature;

CREATE TEMP TABLE _catalog_title_content_match ON COMMIT DROP AS
SELECT DISTINCT
    left_release.title_id AS left_title_id,
    right_release.title_id AS right_title_id,
    left_release.id AS left_release_id,
    right_release.id AS right_release_id,
    left_signature.rom_count AS matched_rom_count,
    left_signature.sha1_set_digest
FROM catalog.release_content_signature left_signature
JOIN catalog.release left_release
  ON left_release.id = left_signature.release_id
JOIN catalog.title left_title ON left_title.id = left_release.title_id
JOIN catalog.release_content_signature right_signature
  ON right_signature.package_count = left_signature.package_count
 AND right_signature.rom_count = left_signature.rom_count
 AND right_signature.sha1_set_digest = left_signature.sha1_set_digest
JOIN catalog.release right_release
  ON right_release.id = right_signature.release_id
 AND right_release.title_id > left_release.title_id
JOIN catalog.title right_title
  ON right_title.id = right_release.title_id
 AND right_title.system_id = left_title.system_id;

INSERT INTO _title_content_match (
    left_title_id, right_title_id, left_release_id, right_release_id,
    matched_rom_count, sha1_set_digest
)
SELECT left_title_id, right_title_id, left_release_id, right_release_id,
    matched_rom_count, sha1_set_digest
FROM _catalog_title_content_match
ORDER BY left_release_id, right_release_id;

CREATE TEMP TABLE _catalog_title_component ON COMMIT DROP AS
WITH RECURSIVE
edge AS (
    SELECT DISTINCT left_title_id AS from_title_id,
        right_title_id AS to_title_id
    FROM _catalog_title_content_match
    UNION
    SELECT DISTINCT right_title_id, left_title_id
    FROM _catalog_title_content_match
),
participating_title AS (
    SELECT from_title_id AS title_id FROM edge
    UNION
    SELECT to_title_id FROM edge
),
reach(root_title_id, title_id) AS (
    SELECT title_id, title_id FROM participating_title
    UNION
    SELECT reach.root_title_id, edge.to_title_id
    FROM reach
    JOIN edge ON edge.from_title_id = reach.title_id
)
SELECT title_id, min(root_title_id) AS component_id
FROM reach
GROUP BY title_id;

CREATE TEMP TABLE _catalog_title_component_summary ON COMMIT DROP AS
SELECT
    component.component_id,
    count(DISTINCT component.title_id)::integer AS component_title_count,
    count(DISTINCT (
        match.left_release_id, match.right_release_id
    ))::integer AS evidence_pair_count
FROM _catalog_title_component component
JOIN _catalog_title_content_match match
  ON match.left_title_id = component.title_id
  OR match.right_title_id = component.title_id
GROUP BY component.component_id;

CREATE TEMP TABLE _catalog_title_representative ON COMMIT DROP AS
WITH title_stats AS (
    SELECT
        component.component_id,
        component.title_id,
        title.display_title,
        count(release.id) AS release_count,
        count(release.id) FILTER (
            WHERE source.fact_value = 'No-Intro'
        ) AS no_intro_release_count,
        min(CASE source.fact_value
            WHEN 'No-Intro' THEN 1
            WHEN 'Redump' THEN 2
            WHEN 'TOSEC' THEN 3
            WHEN 'TOSEC-ISO' THEN 4
            ELSE 5
        END) AS source_priority
    FROM _catalog_title_component component
    JOIN catalog.title title ON title.id = component.title_id
    JOIN catalog.release release ON release.title_id = component.title_id
    JOIN catalog.release_fact source
      ON source.release_id = release.id
     AND source.fact_key = 'source_collection'
    GROUP BY component.component_id, component.title_id, title.display_title
),
ranked AS (
    SELECT title_stats.*,
        row_number() OVER (
            PARTITION BY component_id
            ORDER BY source_priority,
                no_intro_release_count DESC,
                release_count DESC,
                lower(display_title), display_title, title_id
        ) AS representative_rank
    FROM title_stats
)
SELECT component_id, title_id AS preferred_title_id
FROM ranked
WHERE representative_rank = 1;

INSERT INTO catalog.title_alias (
    alias_title_id, preferred_title_id, match_basis,
    component_title_count, evidence_pair_count
)
SELECT component.title_id, representative.preferred_title_id,
    'exact_content_component', summary.component_title_count,
    summary.evidence_pair_count
FROM _catalog_title_component component
JOIN _catalog_title_representative representative USING (component_id)
JOIN _catalog_title_component_summary summary USING (component_id)
WHERE component.title_id <> representative.preferred_title_id
ORDER BY component.title_id;
