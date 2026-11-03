"""Reviewed genre aliases shared by both metadata providers."""
import csv
import re
import unicodedata


def genre_key(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def read_genre_aliases(path):
    aliases = {}
    with open(path, newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            alias, canonical = genre_key(row['alias']), row['canonical_genre'].strip()
            if not alias or not canonical:
                raise ValueError('genre aliases must not be blank')
            for key in (alias, genre_key(canonical)):
                if key in aliases and aliases[key] != canonical:
                    raise ValueError(f'conflicting genre alias: {key}')
                aliases[key] = canonical
    return aliases


def genre_values(value, provider, aliases):
    # LaunchBox uses semicolons; RDB also has explicit spaced-slash lists.
    # Keep hierarchy colons and embedded slashes (Copy/Backup) intact.
    parts = re.split(r';|\s+/\s+', value) if provider == 'libretro-database' else value.split(';')
    return sorted({aliases.get(genre_key(part), part.strip())
                   for part in parts if part.strip()})


def normalize_genres(c, root):
    """Expand claims, coalescing aliases within a provider without losing evidence."""
    from sqlalchemy import text

    aliases = read_genre_aliases(root / 'reference/genre_aliases.csv')
    rows = c.execute(text("""SELECT DISTINCT source_provider, fact_value
        FROM catalog.software_fact WHERE fact_key='genre'""")).all()
    c.exec_driver_sql('''CREATE TEMP TABLE _genre_mapping (
        source_provider text, original_value text, fact_value text,
        PRIMARY KEY (source_provider, original_value, fact_value)
    ) ON COMMIT DROP''')
    mappings = [dict(provider=provider, original=original, value=value)
                for provider, original in rows
                for value in genre_values(original, provider, aliases)]
    if mappings:
        c.execute(text('INSERT INTO _genre_mapping VALUES (:provider,:original,:value)'), mappings)
    c.exec_driver_sql('''
        CREATE TEMP TABLE _genre_claim ON COMMIT DROP AS
        SELECT DISTINCT f.software_id, m.fact_value, f.source_provider, f.source_revision,
            e.source_file_id, e.source_row_number, e.source_database,
            e.source_relative_path, e.matched_sha1, e.match_method,
            e.match_details || jsonb_build_object('original_genre', f.fact_value) AS match_details
        FROM catalog.software_fact f
        JOIN _genre_mapping m ON m.source_provider=f.source_provider AND m.original_value=f.fact_value
        JOIN catalog.software_fact_evidence e ON e.software_fact_id=f.id
        WHERE f.fact_key='genre';

        DELETE FROM catalog.software_fact WHERE fact_key='genre';

        INSERT INTO catalog.software_fact (
            software_id,fact_key,fact_value,source_provider,source_revision,
            source_record_count,matched_content_count,value_rank,value_count)
        SELECT software_id,'genre',fact_value,source_provider,source_revision,
            count(DISTINCT (source_file_id,source_row_number)),count(DISTINCT matched_sha1),1,1
        FROM _genre_claim
        GROUP BY software_id,fact_value,source_provider,source_revision;

        INSERT INTO catalog.software_fact_evidence (
            software_fact_id,source_file_id,source_row_number,source_database,
            source_relative_path,matched_sha1,match_method,match_details)
        SELECT f.id,c.source_file_id,c.source_row_number,min(c.source_database),
            min(c.source_relative_path),min(c.matched_sha1),min(c.match_method),
            (jsonb_agg(c.match_details ORDER BY c.match_details::text)->0)
                || jsonb_build_object('original_genres', jsonb_agg(DISTINCT c.match_details->>'original_genre'))
        FROM _genre_claim c JOIN catalog.software_fact f
          ON f.software_id=c.software_id AND f.fact_key='genre' AND f.fact_value=c.fact_value
         AND f.source_provider=c.source_provider AND f.source_revision=c.source_revision
        GROUP BY f.id,c.source_file_id,c.source_row_number;
    ''')
