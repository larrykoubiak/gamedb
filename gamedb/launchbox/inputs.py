"""Read matching inputs within the caller's transaction."""
from collections import defaultdict
from sqlalchemy import select, text
from . import schema


def load_inputs(c, revision=None):
    query = select(schema.snapshot).order_by(schema.snapshot.c.imported_at.desc(), schema.snapshot.c.id.desc())
    if revision:
        query = query.where(schema.snapshot.c.source_revision == revision)
    snapshot = c.execute(query.limit(1)).mappings().one_or_none()
    if not snapshot:
        raise ValueError("no LaunchBox snapshot found; import a ZIP first")
    games = {}
    aliases = defaultdict(set)
    for row in c.execute(select(schema.record.c.record_type, schema.record.c.database_id, schema.record.c.raw_record).where(
        schema.record.c.import_id == snapshot["id"],
        schema.record.c.record_type.in_(["Game", "GameAlternateName"]),
    )):
        kind, game_id, fields = row
        if kind == "Game":
            if game_id in games:
                raise ValueError(f"duplicate LaunchBox Game DatabaseID: {game_id}")
            games[game_id] = fields
        elif fields.get("AlternateName"):
            aliases[game_id].add(fields["AlternateName"])
    software = [dict(row) for row in c.execute(text('''
        SELECT w.id, s.manufacturer_name, s.system_name, w.display_name,
               w.identity_basis
        FROM catalog.software w JOIN catalog.system s ON s.id=w.system_id
        ORDER BY w.id
    ''')).mappings()]
    by_id = {item["id"]: item for item in software}
    for item in software:
        item["titles"] = {item["display_name"]}
    for software_id, title in c.execute(text('''
        SELECT DISTINCT sr.software_id, t.display_title
        FROM catalog.software_release sr
        JOIN catalog.release r ON r.id=sr.release_id
        JOIN catalog.title t ON t.id=r.title_id
    ''')):
        by_id[software_id]["titles"].add(title)
    for item in software:
        item["match_facts"] = defaultdict(set)
    for software_id, key, value in c.execute(text("""
        SELECT DISTINCT sr.software_id, f.fact_key, f.fact_value
        FROM catalog.software_release sr
        JOIN catalog.release_fact f ON f.release_id=sr.release_id
        WHERE f.fact_key IN ('release_date', 'publisher', 'developer')
    """)):
        by_id[software_id]["match_facts"][key].add(value)
    for software_id, key, value in c.execute(text("""
        SELECT software_id, fact_key, fact_value FROM catalog.software_fact
        WHERE fact_key IN ('publisher', 'developer') AND source_provider <> 'launchbox'
    """)):
        by_id[software_id]["match_facts"][key].add(value)
    existing = defaultdict(set)
    for software_id, fact_key in c.execute(text("SELECT DISTINCT software_id, fact_key FROM catalog.software_fact")):
        existing[software_id].add(fact_key)
    return snapshot, games, aliases, software, existing
