"""Resolve same-platform soundtrack matches and publish one complete inventory."""

import json
from collections import Counter, defaultdict
from itertools import islice

from sqlalchemy import bindparam, text

from gamedb.catalog.software_identity import SOFTWARE_KEY_SQL
from gamedb.config import PROJECT_ROOT

from .inventory import C64
from .joshw import COLLECTION as JOSHW_COLLECTION, supports_version, title_revision
from .matching import (
    EXTENDED_SYSTEMS,
    YEAR,
    TitleIndex,
    joshw_regional_hits,
    match_sid,
    match_titles,
    psf_album,
    publisher_key,
    reviewed_titles,
    sid_claim,
    snes_filename_titles,
)

CANDIDATES = text(f"""
    WITH scoped AS MATERIALIZED (
        SELECT software.id, software.display_name, system.manufacturer_name, system.system_name,
               {SOFTWARE_KEY_SQL} AS target_key
        FROM catalog.software software
        JOIN catalog.system system ON system.id = software.system_id
        JOIN catalog.title title ON title.id = software.preferred_title_id
        WHERE (system.manufacturer_name, system.system_name) IN :systems
    )
    SELECT scoped.*, scoped.display_name AS name FROM scoped
    UNION
    SELECT scoped.*, title.display_title AS name
    FROM scoped JOIN catalog.software_release membership ON membership.software_id = scoped.id
    JOIN catalog.release release ON release.id = membership.release_id
    JOIN catalog.title title ON title.id = release.title_id
    ORDER BY id, name
""").bindparams(bindparam("systems", expanding=True))

LAUNCHBOX_NAMES = text("""
    SELECT DISTINCT fact.software_id, evidence.match_details->>'source_title' AS title,
           evidence.match_details->'source_aliases' AS aliases,
           evidence.match_details->>'database_id' AS database_id
    FROM catalog.software_fact fact
    JOIN catalog.software_fact_evidence evidence ON evidence.software_fact_id = fact.id
    WHERE fact.software_id = ANY(:software_ids) AND fact.source_provider = 'launchbox'
      AND fact.fact_key = 'description'
    ORDER BY fact.software_id, title, database_id
""")

RELEASE_CREDITS = text("""
    SELECT DISTINCT membership.software_id, released.fact_value, publisher.fact_value
    FROM catalog.software_release membership
    JOIN catalog.release_fact released ON released.release_id = membership.release_id
     AND released.fact_key = 'release_date'
    JOIN catalog.release_fact publisher ON publisher.release_id = membership.release_id
     AND publisher.fact_key = 'publisher'
    WHERE membership.software_id = ANY(:software_ids)
""")

RELEASE_VERSIONS = text("""
    SELECT DISTINCT membership.software_id, fact.fact_key, fact.fact_value
    FROM catalog.software_release membership
    JOIN catalog.release_fact fact ON fact.release_id = membership.release_id
    WHERE membership.software_id = ANY(:software_ids) AND fact.fact_key IN ('revision', 'version')
""")

INSERT_SOUNDTRACK = text("""
    INSERT INTO vgm.soundtrack (key, collection, source_name, title, platform,
                                aliases, status, target_key, additional_target_keys,
                                candidates, match_evidence, issues)
    VALUES (:key, :collection, :source_name, :title, :platform, :aliases, :status,
            :target_key, :additional_target_keys, CAST(:candidates AS jsonb),
            CAST(:match_evidence AS jsonb), :issues)
""")
INSERT_ASSET = text("""
    INSERT INTO vgm.asset (key, soundtrack_key, position, detail)
    VALUES (:key, :soundtrack_key, :position, CAST(:detail AS jsonb))
""")


def catalog_index(connection, names, *, spelling_systems=()):
    index = TitleIndex(names, spelling_systems=spelling_systems)
    systems = sorted({platform for platform, _ in names})
    if not systems:
        return index

    alias_targets = {}
    for row in connection.execute(CANDIDATES, {"systems": systems}).mappings():
        platform = (row["manufacturer_name"], row["system_name"])
        index.add(platform, row)
        if platform in EXTENDED_SYSTEMS:
            alias_targets.setdefault(row["id"], (platform, dict(row)))
    if alias_targets and connection.execute(text("""
        SELECT to_regclass('catalog.software_fact') IS NOT NULL
           AND to_regclass('catalog.software_fact_evidence') IS NOT NULL
    """)).scalar_one():
        for row in connection.execute(LAUNCHBOX_NAMES, {"software_ids": sorted(alias_targets)}).mappings():
            platform, target = alias_targets[row["software_id"]]
            if row["database_id"] is None:
                continue
            for name in (row["title"], *(row["aliases"] or [])):
                if name:
                    index.add(platform, {**target, "name": name}, database_id=row["database_id"])
    return index


def sid_release_credits(connection, software_ids):
    credits = defaultdict(set)
    ids = sorted(software_ids)
    for start in range(0, len(ids), 500):
        for ident, date, publisher in connection.execute(
            RELEASE_CREDITS, {"software_ids": ids[start:start + 500]}
        ):
            year = YEAR.match(date)
            company = publisher_key(publisher)
            if year and company and company != "pd":
                credits[ident].add((year[1], company))
    return credits


def release_versions(connection, software_ids):
    versions = defaultdict(set)
    if software_ids:
        for ident, kind, value in connection.execute(RELEASE_VERSIONS, {"software_ids": sorted(software_ids)}):
            versions[ident].add((kind, value))
    return versions


def resolve(connection, soundtracks):
    reviewed = reviewed_titles()
    names = set()
    sources = []
    joshw_systems = set()
    for item in soundtracks:
        album = psf_album(item)
        sid = sid_claim(item) if item.system == C64 else None
        review = reviewed.get((item.collection, item.source_name))
        base_title, revision = title_revision(item.title) if item.collection == JOSHW_COLLECTION else (item.title, None)
        sources.append((item, album, sid, review, revision))
        if item.system:
            if item.collection == JOSHW_COLLECTION:
                joshw_systems.add(item.system)
            names.update((item.system, name) for name in
                         (item.title, *item.aliases, *snes_filename_titles(item)))
            if item.collection == JOSHW_COLLECTION:
                names.update((item.system, name) for name in (base_title, item.title.removesuffix(" [fixed]")))
            if album:
                names.add((item.system, album))
            if sid:
                names.add((item.system, sid["album"]))
            if review and review["catalog_title"]:
                names.add((item.system, review["catalog_title"]))

    index = catalog_index(connection, names, spelling_systems=joshw_systems)
    pending = []
    sid_ids = set()
    version_ids = set()
    for item, album, sid, review, revision in sources:
        hits = match_titles(index, item, review, album, sid) if item.system else {}
        alternates = joshw_regional_hits(index, item, revision) if len(hits) == 1 and item.collection == JOSHW_COLLECTION else {}
        if revision:
            version_ids.update(hits.keys() | alternates.keys())
        if sid and sid["year"] and sid["publisher"]:
            sid_ids.update(hits)
        pending.append((item, hits, sid, review, revision, alternates))
    credits = sid_release_credits(connection, sid_ids)
    versions = release_versions(connection, version_ids)

    for item, hits, sid, review, revision, alternates in pending:
        evidence, target = {}, None
        additional = {}
        if revision and len(hits) > 1:
            confirmed = {ident: hit for ident, hit in hits.items() if supports_version(item.system, revision, versions[ident])}
            if len(confirmed) == 1:
                hits = confirmed
        chosen, basis = match_sid(hits, sid, credits) if item.system == C64 and not review else (None, None)
        reviewed_title = bool(review and review["catalog_title"])
        deferred = bool(review and not reviewed_title)
        if chosen is None and len(hits) == 1 and (not item.review_only or reviewed_title) and not deferred:
            chosen = next(iter(hits))
            matched = hits[chosen]
            if "reviewNote" in matched:
                basis = "reviewed_title"
            elif "psfGameTag" in matched:
                basis = "psf_game_tag"
            else:
                basis = item.match_basis
        if chosen is not None:
            additional = {ident: hit for ident, hit in alternates.items() if ident != chosen and (
                not revision or all(supports_version(item.system, revision, versions[key]) for key in (chosen, ident))
            )}
            hits.update(additional)
        candidates = {
            ident: {key: value for key, value in hits[ident].items() if key != "target_key"}
            for ident in sorted(hits)
        }
        if chosen is not None:
            target = hits[chosen]["target_key"]
            evidence = {**candidates[chosen], **item.source_evidence, "basis": basis}
            if revision:
                evidence["joshwVersion"] = revision
            if additional:
                evidence["additionalTitles"] = [candidates[ident] for ident in sorted(additional)]
            if sid:
                evidence.update(sidAlbum=sid["album"], sidCopyright=sid["copyright"])
        if not item.system:
            status = "unclassified"
        elif chosen is not None:
            status = "matched"
        elif len(hits) > 1:
            status = "ambiguous"
        else:
            status = "review" if hits or deferred else "unmatched"
        yield {
            "key": item.key,
            "collection": item.collection,
            "source_name": item.source_name,
            "title": item.title,
            "platform": list(item.system) if item.system else None,
            "aliases": list(item.aliases) + ([review["catalog_title"]]
                                             if review and review["catalog_title"] else []),
            "status": status,
            "target_key": target,
            "additional_target_keys": sorted(hit["target_key"] for hit in additional.values()),
            "candidates": list(candidates.values()),
            "match_evidence": evidence,
            "issues": [*item.issues, review["evidence"]] if deferred else item.issues,
        }


def publish(connection, soundtracks, resolved):
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('gamedb.vgm.publish'))"))
    connection.exec_driver_sql((PROJECT_ROOT / "sql/layers/vgm/schema.sql").read_text())
    connection.execute(text("DELETE FROM vgm.soundtrack"))
    for start in range(0, len(resolved), 1000):
        connection.execute(INSERT_SOUNDTRACK, [
            {"additional_target_keys": [], **row, "candidates": json.dumps(row["candidates"]),
             "match_evidence": json.dumps(row["match_evidence"])}
            for row in resolved[start:start + 1000]
        ])
    assets = (
        {"key": asset["key"], "soundtrack_key": item.key, "position": position,
         "detail": json.dumps(asset)}
        for item in soundtracks for position, asset in enumerate(item.assets)
    )
    while batch := list(islice(assets, 1000)):
        connection.execute(INSERT_ASSET, batch)


def summarize(soundtracks, resolved):
    collections = defaultdict(Counter)
    for item, result in zip(soundtracks, resolved, strict=True):
        counts = collections[item.collection]
        counts["sets"] += 1
        counts[result["status"]] += 1
        if result["match_evidence"]:
            counts[result["match_evidence"]["basis"]] += 1
        for asset in item.assets:
            counts[asset["kind"]] += 1
        if item.issues:
            counts["sets_with_issues"] += 1
    return {"totals": dict(sum(collections.values(), Counter())), "collections": collections}
