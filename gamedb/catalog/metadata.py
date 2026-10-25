"""Atomically rebuild attributed RDB and LaunchBox software metadata."""
from collections import Counter
from pathlib import Path

from sqlalchemy import BigInteger, Column, MetaData, Table, Text, insert, text
from sqlalchemy.dialects.postgresql import JSONB

from gamedb.launchbox.inputs import load_inputs
from gamedb.launchbox.importer import sha256_file
from gamedb.launchbox.matching import FACT_FIELDS, MATCHER_VERSION, match_candidates, read_platform_map


def sql_body(path):
    # These repository-owned scripts also remain readable by psql. The Python
    # builder owns the transaction and handles their optional-source branches.
    return '\n'.join(line for line in path.read_text().splitlines()
                     if not line.startswith('\\') and line.strip() not in {'BEGIN;', 'COMMIT;'})


def build_metadata(engine, root):
    root = Path(root)
    sql = root / 'sql/layers/metadata'
    counts = Counter()
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        c.execute(text('SELECT pg_advisory_xact_lock(721044282)'))
        # Prevent identity rebuilds while reading and publishing build-local IDs.
        c.execute(text('LOCK TABLE catalog.software IN SHARE MODE'))
        ddl = sql_body(sql / '010_schema.sql').split('-- A catalog rebuild')[0]
        c.execute(text(ddl))
        has_rdb = c.execute(text("SELECT to_regclass('staging.libretro_rdb_entry') IS NOT NULL AND to_regclass('staging.libretro_rdb_import') IS NOT NULL AND to_regclass('staging.libretro_rdb_file') IS NOT NULL")).scalar_one()
        if has_rdb:
            c.execute(text(sql_body(sql / '020_build.sql')))
        has_launchbox = c.execute(text("SELECT to_regclass('staging.launchbox_record') IS NOT NULL AND to_regclass('staging.launchbox_import') IS NOT NULL")).scalar_one()
        if has_launchbox:
            has_import = c.execute(text('SELECT EXISTS (SELECT 1 FROM staging.launchbox_import)')).scalar_one()
            if has_import:
                counts = project_launchbox(c, root)
        # Exact-content evidence ranks ahead of title-based evidence. Both
        # sources remain visible, including disagreements, without overwrites.
        c.exec_driver_sql('''
            WITH ranked AS (
                SELECT id,
                    dense_rank() OVER (PARTITION BY software_id, fact_key
                        ORDER BY matched_content_count DESC, source_record_count DESC) AS rank,
                    count(*) OVER (PARTITION BY software_id, fact_key) AS total
                FROM catalog.software_fact
            )
            UPDATE catalog.software_fact f SET value_rank=r.rank, value_count=r.total
            FROM ranked r WHERE f.id=r.id
        ''')
        c.execute(text(sql_body(sql / '090_indexes_and_validation.sql')))
    return dict(counts)


def project_launchbox(c, root):
    snapshot, games, aliases, software, _ = load_inputs(c)
    path = root / 'reference/launchbox_platforms.csv'
    platforms = read_platform_map(path)
    mapping_revision = sha256_file(path)
    known = {game['Platform'] for game in games.values()}
    missing = {p for values in platforms.values() for p in values} - known
    if missing:
        raise ValueError(f'LaunchBox platform mappings absent from snapshot: {sorted(missing)}')
    matches = match_candidates(software, games, aliases, platforms)
    row_numbers = dict(c.execute(text('''SELECT database_id,row_number
        FROM staging.launchbox_record WHERE import_id=:id AND record_type='Game'
    '''), {'id': snapshot['id']}).all())
    by_id = {item['id']: item for item in software}
    c.exec_driver_sql('''CREATE TEMP TABLE _launchbox_claim (
        software_id bigint, fact_key text, fact_value text, source_row_number bigint,
        source_database text, match_method text, match_details jsonb
    ) ON COMMIT DROP''')
    claim_table = Table('_launchbox_claim', MetaData(),
        Column('software_id', BigInteger), Column('fact_key', Text),
        Column('fact_value', Text), Column('source_row_number', BigInteger),
        Column('source_database', Text), Column('match_method', Text),
        Column('match_details', JSONB))
    insert_claim = insert(claim_table)
    batch = []
    counts = Counter()
    for match in matches:
        game_id = match['selected_database_id']
        if game_id is None:
            continue
        item = by_id[match['software_id']]
        game = games[game_id]
        details = dict(
            database_id=game_id, candidate_ids=match['database_ids'],
            matcher_version=MATCHER_VERSION, platform_map_sha256=mapping_revision,
            resolution_basis=match['resolution_basis'],
            catalog_titles=sorted(item['titles']),
            match_facts={key: sorted(values) for key, values in item['match_facts'].items()},
            source_title=game['Name'], source_aliases=sorted(aliases.get(game_id, ())),
        )
        counts['selected_software'] += 1
        for key, field in FACT_FIELDS.items():
            value = game.get(field, '').strip()
            if not value:
                continue
            batch.append(dict(software_id=item['id'], fact_key=key, fact_value=value,
                              source_row_number=row_numbers[game_id], source_database=game['Platform'],
                              match_method=match['status'], match_details=details))
            counts[key] += 1
            if len(batch) >= 2000:
                c.execute(insert_claim, batch)
                batch.clear()
    if batch:
        c.execute(insert_claim, batch)
    c.execute(text('''INSERT INTO catalog.software_fact (
        software_id,fact_key,fact_value,source_provider,source_revision,
        source_record_count,matched_content_count,value_rank,value_count)
        SELECT software_id,fact_key,fact_value,'launchbox',:revision,1,0,1,1
        FROM _launchbox_claim
    '''), {'revision': snapshot['source_revision']})
    c.execute(text('''INSERT INTO catalog.software_fact_evidence (
        software_fact_id,source_file_id,source_row_number,source_database,
        source_relative_path,matched_sha1,match_method,match_details)
        SELECT f.id,:import_id,claim.source_row_number,claim.source_database,
            'Metadata.xml',NULL,claim.match_method,claim.match_details
        FROM _launchbox_claim claim JOIN catalog.software_fact f
          ON f.software_id=claim.software_id AND f.fact_key=claim.fact_key
         AND f.source_provider='launchbox' AND f.source_revision=:revision
    '''), {'import_id': snapshot['id'], 'revision': snapshot['source_revision']})
    return counts
