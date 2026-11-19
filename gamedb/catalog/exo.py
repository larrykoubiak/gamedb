"""Publish reviewed eXo browse identities, source metadata, and related media atomically."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest
from pathlib import Path

from sqlalchemy import MetaData, Table, text

from gamedb.config import PROJECT_ROOT
from gamedb.exo.editions import SUFFIX, key, runtime_index, source_editions
from gamedb.exo.media import open_location

SQL = PROJECT_ROOT / "sql/layers/exo"
SHELVES = {"MS-DOS": 1_000_001, "Windows 9x": 1_000_002, "ScummVM": 1_000_003}
FACTS = {
    "Notes": "description",
    "Genre": "genre",
    "Developer": "developer",
    "Publisher": "publisher",
    "Series": "franchise",
    "MaxPlayers": "player_count",
    "PlayMode": "play_mode",
    "Rating": "rating",
    "Region": "region",
    "Language": "language",
    "ReleaseDate": "release_date",
    "ReleaseYear": "release_year",
    "ReleaseType": "release_type",
    "Version": "version",
    "SortTitle": "sort_title",
    "Status": "status",
    "Source": "source",
    "WikipediaURL": "wikipedia_url",
    "VideoUrl": "video_url",
    "CommunityStarRating": "community_rating",
    "CommunityStarRatingTotalVotes": "community_rating_votes",
}
MULTIPLE = {"Genre", "Series", "PlayMode", "Region", "Language"}
ART = {
    "Box - Front": "boxart",
    "Screenshot - Gameplay": "snap",
    "Screenshot - Game Title": "title",
    "Clear Logo": "logo",
}
BUILD_VERSION = "exo-browse-2"


def source_facts(fields, aliases):
    result = {}
    for field, name in FACTS.items():
        value = fields.get(field)
        if value and value.strip():
            if field == "Notes":
                result[name] = [value]
                continue
            values = value.split(";") if field in MULTIPLE else [value]
            result[name] = list(dict.fromkeys(v.strip() for v in values if v.strip()))
    if aliases:
        result["alternate_title"] = list(
            dict.fromkeys(a["Name"] for a in aliases if a.get("Name"))
        )
    return result


def name_key(name):
    name = name.casefold().strip()
    if name.endswith(", the"):
        name = "the " + name[:-5]
    return " ".join(re.findall(r"\w+", name))


def work_evidence(game, entry_key):
    fields = game["fields"]
    # All four pieces must agree; the source demonstrably reuses database IDs.
    evidence = [
        fields.get("DatabaseID", ""),
        name_key(game["label"]),
        fields.get("ReleaseDate", "")[:4],
        name_key(fields.get("Developer", "")),
    ]
    return key("exo:work", *evidence) if all(evidence) else entry_key


def publisher_key(value):
    return re.sub(
        r"(?: (?:incorporated|inc|corporation|corp|limited|ltd|llc|gmbh))+$",
        "",
        name_key(value),
    )


def public_id(work, namespace):
    # This source namespace fits in an exact JavaScript integer. Relational
    # uniqueness checks reject collisions, even on a different rebuild.
    return (1 << 49) + int(key(work, namespace)[:12], 16)


def insert_rows(connection, name, rows):
    if rows:
        table = Table(name, MetaData(), schema="catalog", autoload_with=connection)
        for offset in range(0, len(rows), 1000):
            connection.execute(table.insert(), rows[offset : offset + 1000])


def existing_pc_releases(db):
    candidates = defaultdict(set)
    sql = """
        SELECT sw.id,r.display_title,sw.display_name,
               max(f.fact_value) FILTER (WHERE f.fact_key='release_date') AS released,
               max(f.fact_value) FILTER (WHERE f.fact_key='publisher') AS publisher
        FROM catalog.system s JOIN catalog.software sw ON sw.system_id=s.id
        JOIN catalog.software_release sr ON sr.software_id=sw.id
        JOIN catalog.release r ON r.id=sr.release_id JOIN catalog.release_fact f ON f.release_id=r.id
        WHERE s.manufacturer_name='IBM' AND s.system_name='PC Compatibles'
          AND f.fact_key IN ('release_date','publisher')
        GROUP BY sw.id,r.id
        HAVING count(DISTINCT f.fact_value) FILTER (WHERE f.fact_key='publisher')=1
           AND count(DISTINCT f.fact_value) FILTER (WHERE f.fact_key='release_date')=1
    """
    for sw, name, display, date, publisher in db.execute(text(sql)):
        for alias in {name_key(name), name_key(display)}:
            if publisher_key(publisher) not in ("", "unknown", "various"):
                candidates[alias, date[:4], publisher_key(publisher)].add(sw)
    return candidates


def launchbox_matches(db):
    claims = defaultdict(list)
    query = """
        SELECT DISTINCT sw.id,sw.system_id,ev.match_details FROM catalog.software_fact f
        JOIN catalog.software sw ON sw.id=f.software_id
        JOIN catalog.software_fact_evidence ev ON ev.software_fact_id=f.id
        WHERE f.source_provider='launchbox' AND f.fact_key='description'
        AND sw.system_id IN (SELECT DISTINCT system_id FROM catalog.exo_edition)
        AND ev.match_details->>'database_id' IN (SELECT fields->>'DatabaseID' FROM catalog.exo_entry)
    """
    for sw, system, evidence in db.execute(text(query)):
        fields = evidence.get("match_facts", {})
        claims[
            system, str(evidence["database_id"]), name_key(evidence["source_title"])
        ].append(
            (
                sw,
                {d[:4] for d in fields.get("release_date", [])},
                {publisher_key(p) for p in fields.get("publisher", [])},
                {name_key(d) for d in fields.get("developer", [])},
            )
        )
    return claims


def read_editions(db, snapshot, root):
    games = (
        db.execute(text((SQL / "entries.sql").read_text()), {"snapshot": snapshot})
        .mappings()
        .all()
    )
    index = runtime_index(
        db.execute(
            text("""SELECT content FROM staging.exo_document
        WHERE snapshot_id=:snapshot AND document_path='eXo/util/scummvm.txt'"""),
            {"snapshot": snapshot},
        ).scalar()
        or b""
    )
    dos_index = (
        db.execute(
            text("""SELECT content FROM staging.exo_document
        WHERE snapshot_id=:snapshot AND document_path='eXo/util/dosbox.txt'"""),
            {"snapshot": snapshot},
        ).scalar()
        or b""
    )
    dos_runners = {
        name.casefold(): version.strip()
        for name, version in (
            line.rsplit(":", 1)
            for line in dos_index.decode("cp1252").splitlines()
            if ":" in line
        )
    }
    systems = {
        (m, n): i
        for i, m, n in db.execute(
            text("SELECT id,manufacturer_name,system_name FROM catalog.system")
        )
    }
    entries, editions = [], []
    anchors = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for game, choices in zip(
            games,
            pool.map(lambda g: source_editions(root, g, index, dos_runners), games),
            strict=True,
        ):
            source, guid = game["platform"], game["game_id"]
            entry = key("exo:entry", source, guid)
            evidence = work_evidence(game, entry)
            priority = (source.startswith("ScummVM"), source != "MS-DOS", entry)
            if evidence not in anchors or priority < anchors[evidence][0]:
                anchors[evidence] = priority, entry
            entries.append(
                {
                    "entry_key": entry,
                    "source_list": source,
                    "game_id": guid,
                    "record_no": game["record_no"],
                    "document_path": game["document_path"],
                    "title": game["label"],
                    "package_path": game["package"],
                    "fields": game["fields"],
                    "aliases": game["aliases"],
                    "facts": source_facts(game["fields"], game["aliases"]),
                }
            )
            if not choices:
                raise ValueError(f"{game['label']} has no source editions")
            for choice in choices:
                variant_title = (
                    SUFFIX.sub("", choice.label).strip()
                    if choice.work_variant
                    else game["label"]
                )
                editions.append(
                    {
                        "edition_key": key("exo:edition", entry, choice.selection),
                        "entry_key": entry,
                        "work_key": key(entry, choice.work_variant)
                        if choice.work_variant
                        else evidence,
                        "work_title": variant_title,
                        "selection": choice.selection,
                        "label": choice.label,
                        "environment": choice.environment,
                        "system_id": systems.get(choice.system),
                        "platform_basis": choice.evidence,
                        "runner": choice.runner,
                        "engine_game": choice.engine_game or None,
                        "runner_version": choice.runner_version or None,
                        "is_mod": game["fields"].get("ReleaseType") == "ROM Hack"
                        or choice.engine_game == "groovie:11hsu"
                        or bool(
                            re.search(
                                r"\((?:ROM Hack|Trainer)\)", choice.label, re.IGNORECASE
                            )
                        ),
                    }
                )
    for edition in editions:
        anchor = anchors.get(edition["work_key"])
        if anchor:
            edition["work_key"] = anchor[1]
    return entries, editions, {i: (m, n) for (m, n), i in systems.items()}


def compile_browse(db, entries, editions, systems, revision):
    games = {g["entry_key"]: g for g in entries}
    pc = next(i for i, s in systems.items() if s == ("IBM", "PC Compatibles"))
    candidates = existing_pc_releases(db)
    external = launchbox_matches(db)
    matches = defaultdict(set)
    bases = defaultdict(set)
    for e in editions:
        game = games[e["entry_key"]]
        if not e["system_id"] or e["work_title"] != game["title"]:
            continue
        facts = game["fields"]
        title, year = name_key(game["title"]), facts.get("ReleaseDate", "")[:4]
        publisher, developer = (
            publisher_key(facts.get("Publisher", "")),
            name_key(facts.get("Developer", "")),
        )
        group = e["work_key"], e["system_id"]
        if e["system_id"] == pc:
            ids = candidates.get((title, year, publisher), ())
            if ids:
                matches[group].update(ids)
                bases[group].add("PC release title, year and publisher")
        for sw, years, publishers, developers in external[
            e["system_id"], facts.get("DatabaseID"), title
        ]:
            if year in years and (publisher in publishers or developer in developers):
                matches[group].add(sw)
                bases[group].add("platform, LaunchBox ID, title, year and credits")
    # Reconcile independent records only when each side has a single candidate.
    reverse = Counter(next(iter(ids)) for ids in matches.values() if len(ids) == 1)
    resolved = {
        wk: next(iter(ids))
        for wk, ids in matches.items()
        if len(ids) == 1 and reverse[next(iter(ids))] == 1
    }
    art = defaultdict(dict)
    for owner, asset, category in db.execute(
        text("""
        SELECT l.owner_key,a.asset_key,a.category FROM catalog.exo_asset_link l
        JOIN catalog.related_asset a USING(asset_key) WHERE a.kind='artwork'
        AND a.category IN ('Box - Front','Screenshot - Gameplay','Screenshot - Game Title','Clear Logo')
        ORDER BY l.owner_key,a.category,(a.region IS NOT NULL),a.logical_path
    """)
    ):
        art[owner].setdefault(
            ART[category], {"path": f"exo/{revision}/{asset}", "provider": "exo"}
        )
    if art:
        db.execute(
            text("""UPDATE catalog.exo_entry e SET tile_media=a.value
                 FROM jsonb_each(CAST(:media AS jsonb)) a WHERE e.entry_key=a.key"""),
            {"media": json.dumps(art)},
        )
    groups = defaultdict(list)
    for e in editions:
        g = games[e["entry_key"]]
        sys_id, work = e["system_id"], e["work_key"]
        shelf = (
            "ScummVM" if g["source_list"].startswith("ScummVM") else g["source_list"]
        )
        canonical = resolved.get((work, sys_id))
        physical_id = canonical or public_id(
            work, str(systems[sys_id]) if sys_id else e["environment"]
        )
        groups[0, physical_id].append(e)
        if sys_id:
            groups[sys_id, physical_id].append(e)
        shelves = {shelf}
        if e["environment"] == "MS-DOS":
            shelves.add("MS-DOS")
        for name in sorted(shelves):
            groups[SHELVES[name], public_id(work, "collection")].append(e)
    result = []
    for (scope, software_id), choices in groups.items():
        # Stable and unmodified editions lead their own platform/collection.
        order = sorted(
            choices,
            key=lambda e: (
                e["is_mod"],
                games[e["entry_key"]]["source_list"].endswith(" SVN"),
                games[e["entry_key"]]["source_list"].startswith("ScummVM"),
                e["selection"].casefold(),
                e["edition_key"],
            ),
        )
        e = order[0]
        work = e["work_key"]
        if any(c["work_key"] != work for c in choices):
            raise ValueError("Ambiguous source software ID")
        g = games[e["entry_key"]]
        media, names = {}, set()
        for choice in order:
            owner = games[choice["entry_key"]]
            names.update(
                [
                    choice["work_title"],
                    choice["label"],
                    owner["title"],
                    *owner["facts"].get("alternate_title", []),
                ]
            )
            for kind, value in art[owner["entry_key"]].items():
                media.setdefault(kind, value)
        m, n = systems.get(e["system_id"], ("eXo", e["environment"]))
        canonical = (
            resolved.get((work, e["system_id"]))
            if scope not in SHELVES.values()
            else None
        )
        result.append(
            {
                "scope_id": scope,
                "software_id": software_id,
                "work_key": work,
                "entry_key": g["entry_key"],
                "work_title": e["work_title"],
                "system_id": e["system_id"],
                "system_name": n,
                "manufacturer": m,
                "linked_software_id": canonical,
                "match_basis": "; ".join(sorted(bases[work, e["system_id"]]))
                if canonical
                else None,
                "edition_count": len(choices),
                "all_mods": all(c["is_mod"] for c in choices),
                "search_names": sorted(names),
                "media": media,
            }
        )
    return result


def verify_shared_media(db, root):
    candidates = (
        db.execute(
            text("""
        WITH groups AS (SELECT DISTINCT work_key,entry_key FROM catalog.exo_edition),
        files AS (
            SELECT a.asset_key,a.logical_path,min(loc.crc32) crc,min(loc.size_bytes) sz
            FROM catalog.related_asset a JOIN catalog.related_location loc USING(asset_key)
            WHERE a.kind IN ('manual','music','video','extra')
            GROUP BY a.asset_key HAVING count(DISTINCT loc.size_bytes)=1 AND count(DISTINCT loc.crc32)=1
        ), shared AS (
            SELECT g.work_key,lower(regexp_replace(f.logical_path,'^.*/','')) AS name,f.crc,f.sz,
                   array_agg(DISTINCT f.asset_key) keys
            FROM files f JOIN catalog.exo_asset_link l USING(asset_key) JOIN groups g ON g.entry_key=l.owner_key
            GROUP BY 1,2,3,4 HAVING count(DISTINCT f.asset_key)>1
        )
        SELECT DISTINCT ON (loc.asset_key) loc.asset_key,loc.source_path,loc.member_no,loc.member_name,
            loc.size_bytes,loc.crc32,loc.mtime_ns FROM catalog.related_location loc
        JOIN (SELECT DISTINCT unnest(keys) asset_key FROM shared) s USING(asset_key)
        ORDER BY loc.asset_key,loc.member_no,loc.source_path
    """)
        )
        .mappings()
        .all()
    )

    def checksum(row):
        with open_location(root, row) as source:
            return {
                "id": row["asset_key"],
                "digest": file_digest(source, "sha256").hexdigest(),
            }

    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(checksum, candidates))
    if hashes:
        db.execute(
            text(
                "UPDATE catalog.related_asset SET content_sha256=:digest WHERE asset_key=:id"
            ),
            hashes,
        )
    return len(hashes)


def publish_catalog(engine, root=None, *, dry_run=False):
    lock = text("SELECT pg_advisory_xact_lock(hashtext('gamedb:exo:catalog'))")
    schema = (SQL / "schema.sql").read_text()
    if not dry_run:
        # Readers can continue using the last complete catalog during the long source scan.
        with engine.connect() as db, db.begin():
            db.execute(lock)
            db.exec_driver_sql(schema)
    with engine.connect() as db, db.begin() as transaction:
        db.execute(lock)
        if dry_run:
            db.exec_driver_sql(schema)
        if not db.scalar(text("SELECT to_regclass('staging.exo_snapshot')")):
            return {"entries": 0}
        snap = (
            db.execute(
                text("SELECT * FROM staging.exo_snapshot ORDER BY id DESC LIMIT 1")
            )
            .mappings()
            .first()
        )
        if not snap:
            return {"entries": 0}
        root = Path(
            root or os.environ.get("GAMEDB_EXO_ROOT") or snap["source_root"]
        ).resolve(strict=True)
        print("Reading eXo edition menus and game metadata", flush=True)
        entries, editions, systems = read_editions(db, snap["id"], root)
        if len(entries) != snap["counts"]["game_packages"]:
            raise ValueError("Incomplete game-package coverage")
        # One transaction replaces this small, independent projection; native
        # scores, content signatures and installed release IDs are never allocated here.
        for table in (
            "exo_browse",
            "exo_asset_link",
            "related_location",
            "related_asset",
            "exo_edition",
            "exo_entry",
            "exo_shelf",
            "exo_publication",
        ):
            db.exec_driver_sql("DELETE FROM catalog." + table)
        insert_rows(db, "exo_entry", entries)
        insert_rows(db, "exo_edition", editions)
        for statement in (SQL / "assets.sql").read_text().strip().split(";\n\n"):
            db.execute(text(statement), {"snapshot": snap["id"]})
        print("Verifying shared attachments", flush=True)
        verified = verify_shared_media(db, root)
        browse = compile_browse(db, entries, editions, systems, snap["source_revision"])
        digest = hashlib.sha256((BUILD_VERSION + snap["source_revision"]).encode())
        for records in (entries, editions, browse):
            for record in records:
                digest.update(
                    json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
                )
        revision = digest.hexdigest()
        insert_rows(db, "exo_browse", browse)
        insert_rows(
            db,
            "exo_shelf",
            [
                {"id": i, "shelf_key": key("exo:shelf", n)[:32], "name": n}
                for n, i in SHELVES.items()
            ],
        )
        inconsistent = db.scalar(
            text("""
            SELECT count(*) FROM catalog.exo_entry g
            JOIN staging.exo_record r ON r.snapshot_id=:snapshot AND r.record_no=g.record_no
            WHERE g.fields IS DISTINCT FROM r.fields
               OR (CASE WHEN r.fields->>'Notes' ~ '[^[:space:]]' THEN r.fields->>'Notes' END)
                    IS DISTINCT FROM (g.facts->'description'->>0)
               OR NOT EXISTS (SELECT FROM catalog.exo_edition e JOIN catalog.exo_browse b USING(work_key)
                              WHERE e.entry_key=g.entry_key AND b.scope_id=0)
        """),
            {"snapshot": snap["id"]},
        )
        if inconsistent:
            raise ValueError(
                f"{inconsistent} eXo entries lost source metadata or catalog membership"
            )
        db.execute(
            text(
                "INSERT INTO catalog.exo_publication(singleton,revision,source_revision,snapshot_id) VALUES(true,:r,:source,:s)"
            ),
            {"r": revision, "source": snap["source_revision"], "s": snap["id"]},
        )
        for table in (
            "exo_entry",
            "exo_edition",
            "exo_browse",
            "related_asset",
            "related_location",
            "exo_asset_link",
        ):
            db.exec_driver_sql("ANALYZE catalog." + table)
        db.exec_driver_sql((SQL / "scoring.sql").read_text())
        db.execute(text("SELECT app.refresh_exo_scores()"))
        result = {
            "entries": len(entries),
            "editions": len(editions),
            "verified_shared_files": verified,
            "matched_catalog_titles": sum(
                b["linked_software_id"] is not None
                for b in browse
                if b["scope_id"] == 0
            ),
            "descriptions": sum(bool(g["facts"].get("description")) for g in entries),
            "genres": sum(bool(g["facts"].get("genre")) for g in entries),
            "revision": revision,
        }
        if dry_run:
            transaction.rollback()
        return result
