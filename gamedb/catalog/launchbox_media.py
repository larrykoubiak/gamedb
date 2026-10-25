"""Fill artwork gaps from selected LaunchBox metadata links; never replace Libretro."""
from collections import Counter

from sqlalchemy import BigInteger, Column, MetaData, Table, Text, insert, text

from gamedb.catalog.media import region_compatibility, refresh_media_revision
from gamedb.launchbox.image_cache import valid_filename

IMAGE_KINDS = {
    'Box - Front': 'boxart',
    'Screenshot - Gameplay': 'snap',
    'Screenshot - Game Title': 'title',
    'Clear Logo': 'logo',
}
REGIONS = {
    'North America': {'US', 'CA'}, 'United States': {'US'}, 'Europe': {'EU'},
    'Japan': {'JP'}, 'World': {'WORLD'}, 'United Kingdom': {'GB'},
    'Germany': {'DE'}, 'Spain': {'ES'}, 'France': {'FR'}, 'Australia': {'AU'},
    'Italy': {'IT'}, 'Korea': {'KR'}, 'Brazil': {'BR'}, 'Asia': {'AS'},
    'Russia': {'RU'}, 'The Netherlands': {'NL'}, 'Oceania': {'AU', 'NZ'},
    'China': {'CN'}, 'Canada': {'CA'}, 'Sweden': {'SE'}, 'Finland': {'FI'},
    'Norway': {'NO'}, 'Hong Kong': {'HK'}, 'Greece': {'GR'},
}


def image_rank(region, preferred_regions, filename):
    label, rank = region_compatibility(frozenset(REGIONS.get(region, ())), frozenset(preferred_regions))
    # Stable filename breaks otherwise equal choices; no random screenshot picks.
    return label, (rank, filename)


def fill_launchbox_media(engine, username='default'):
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c, c.begin():
        c.execute(text('SELECT pg_advisory_xact_lock(721044283)'))
        present = c.execute(text("""SELECT
            to_regclass('staging.launchbox_image_import') IS NOT NULL
            AND to_regclass('catalog.software_fact_evidence') IS NOT NULL
            AND to_regclass('catalog.software_media') IS NOT NULL""")).scalar_one()
        if not present:
            return {'associations': 0, 'skipped': 'image references or catalog metadata/media unavailable'}
        c.execute(text('LOCK TABLE catalog.software_media, catalog.media IN SHARE ROW EXCLUSIVE MODE'))
        c.execute(text('''
            ALTER TABLE catalog.media DROP CONSTRAINT IF EXISTS media_provider_check;
            ALTER TABLE catalog.media ADD CONSTRAINT media_provider_check
                CHECK (provider IN ('libretro-thumbnails','launchbox'));
            ALTER TABLE catalog.media ADD COLUMN IF NOT EXISTS source_revision text;
            ALTER TABLE catalog.media ADD COLUMN IF NOT EXISTS source_record_id bigint;
            ALTER TABLE catalog.media ADD COLUMN IF NOT EXISTS source_game_id bigint;
            ALTER TABLE catalog.media ADD COLUMN IF NOT EXISTS source_crc32 bigint;
            ALTER TABLE catalog.software_media DROP CONSTRAINT IF EXISTS software_media_match_basis_check;
            ALTER TABLE catalog.software_media ADD CONSTRAINT software_media_match_basis_check
                CHECK (match_basis IN ('preferred_release_exact','software_release_exact',
                    'software_title_fallback','launchbox_metadata'));
        '''))
        # Remove only this provider's previous projection; failed builds roll back.
        c.execute(text("DELETE FROM catalog.media WHERE provider='launchbox'"))
        query = text('''
            WITH links AS MATERIALIZED (
                SELECT DISTINCT f.software_id, e.source_file_id AS import_id,
                    (e.match_details->>'database_id')::bigint AS game_id
                FROM catalog.software_fact f
                JOIN catalog.software_fact_evidence e ON e.software_fact_id=f.id
                JOIN staging.launchbox_import snapshot
                  ON snapshot.id=e.source_file_id AND snapshot.source_revision=f.source_revision
                JOIN staging.launchbox_image_import complete ON complete.import_id=snapshot.id
                WHERE f.source_provider='launchbox'
            ), preferred AS MATERIALIZED (
                SELECT p.software_id,p.release_id,
                    coalesce(array_agg(DISTINCT f.fact_value)
                        FILTER (WHERE f.fact_value IS NOT NULL), ARRAY[]::text[]) AS regions
                FROM app.user_preferred_release p
                JOIN app.app_user u ON u.id=p.user_id AND u.username=:username
                LEFT JOIN catalog.release_fact f ON f.release_id=p.release_id AND f.fact_key='region'
                GROUP BY p.software_id,p.release_id
            )
            SELECT l.software_id,p.release_id,p.regions,i.import_id,i.row_number,
                   i.file_name,i.image_type,i.region
            FROM links l JOIN preferred p ON p.software_id=l.software_id
            JOIN staging.launchbox_image i ON i.import_id=l.import_id AND i.database_id=l.game_id
            WHERE i.image_type IN ('Box - Front','Screenshot - Gameplay','Screenshot - Game Title','Clear Logo')
              AND NOT EXISTS (
                SELECT 1 FROM catalog.software_media sm
                WHERE sm.software_id=l.software_id AND sm.media_kind=CASE i.image_type
                    WHEN 'Box - Front' THEN 'boxart' WHEN 'Screenshot - Gameplay' THEN 'snap'
                    WHEN 'Screenshot - Game Title' THEN 'title' WHEN 'Clear Logo' THEN 'logo' END)
        ''')
        choices = {}
        for row in c.execute(query, {'username': username}):
            if not valid_filename(row.file_name):
                continue
            kind = IMAGE_KINDS[row.image_type]
            label, rank = image_rank(row.region, row.regions, row.file_name)
            key = row.software_id, kind
            if key not in choices or rank > choices[key][0]:
                choices[key] = (rank, dict(software_id=row.software_id, media_kind=kind,
                    release_id=row.release_id, import_id=row.import_id,
                    source_row=row.row_number, region_match=label,
                    relative_path=f'launchbox/{kind}/{row.file_name}'))
        c.execute(text('''CREATE TEMP TABLE _launchbox_media_choice (
            software_id bigint,media_kind text,release_id bigint,import_id bigint,
            source_row bigint,region_match text,relative_path text
        ) ON COMMIT DROP'''))
        table = Table('_launchbox_media_choice', MetaData(),
            Column('software_id', BigInteger), Column('media_kind', Text),
            Column('release_id', BigInteger), Column('import_id', BigInteger),
            Column('source_row', BigInteger), Column('region_match', Text), Column('relative_path', Text))
        rows = [choice[1] for choice in choices.values()]
        for offset in range(0, len(rows), 2000):
            c.execute(insert(table), rows[offset:offset + 2000])
        c.execute(text('''
            INSERT INTO catalog.media (provider,media_kind,source_system_directory,file_name,
                relative_path,source_revision,source_record_id,source_game_id,source_crc32)
            SELECT DISTINCT ON (chosen.relative_path) 'launchbox',chosen.media_kind,'LaunchBox',i.file_name,
                chosen.relative_path,s.source_revision,i.row_number,i.database_id,
                nullif(i.raw_record->>'CRC32','')::bigint
            FROM _launchbox_media_choice chosen
            JOIN staging.launchbox_image i ON i.import_id=chosen.import_id AND i.row_number=chosen.source_row
            JOIN staging.launchbox_import s ON s.id=i.import_id
            ORDER BY chosen.relative_path,i.row_number;
            INSERT INTO catalog.software_media (software_id,media_kind,media_id,match_basis,region_match,source_release_id)
            SELECT chosen.software_id,chosen.media_kind,m.id,'launchbox_metadata',chosen.region_match,chosen.release_id
            FROM _launchbox_media_choice chosen JOIN catalog.media m
              ON m.provider='launchbox' AND m.relative_path=chosen.relative_path;
            ANALYZE catalog.media;
            ANALYZE catalog.software_media;
        '''))
        refresh_media_revision(c)
        counts = Counter(row['media_kind'] for row in rows)
        return dict(associations=len(rows), software=len({row['software_id'] for row in rows}), **counts)
