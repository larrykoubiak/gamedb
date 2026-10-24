"""Retain and resolve separately inventoried FBNeo sample archives."""

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from copy import deepcopy

from sqlalchemy import insert, select, text

from .importer import digest, read_machines
from .resolver import safe_path
from .schema import metadata, samples, source


def import_samples(engine, source_key, dat, dat_path):
    header = ET.parse(dat).getroot().find("header")
    with engine.begin() as connection:
        metadata.create_all(connection)
        src = (
            connection.execute(select(source).where(source.c.source_key == source_key))
            .mappings()
            .one()
        )
        if (
            not source_key.startswith("FBNeo:")
            or header is None
            or header.findtext("name") != "FinalBurn Neo - Samples"
            or header.findtext("version") != src["version"]
        ):
            raise ValueError("Samples DAT must match the FBNeo source version")
        sha256 = digest(dat)
        old = (
            connection.execute(
                select(samples).where(samples.c.source_key == source_key)
            )
            .mappings()
            .all()
        )
        if old:
            if any(
                row["dat_sha256"] != sha256 or row["dat_path"] != dat_path
                for row in old
            ):
                raise ValueError("Samples source already has different inputs")
            return len(old)
        if not connection.execute(
            text(
                "SELECT 1 FROM staging.rv_files WHERE dat_root_full_name=:path LIMIT 1"
            ),
            {"path": dat_path},
        ).first():
            raise ValueError("Samples DAT is absent from rv_files")
        rows = [
            {
                "source_key": source_key,
                "name": d["name"],
                "dat_path": dat_path,
                "dat_sha256": sha256,
                "definition": d,
            }
            for d in read_machines(dat)
        ]
        connection.execute(insert(samples), rows)
        return len(rows)


def load_samples(connection, source_key):
    rows = (
        connection.execute(select(samples).where(samples.c.source_key == source_key))
        .mappings()
        .all()
    )
    definitions = {r["name"]: r["definition"] for r in rows}
    inventory = defaultdict(list)
    if not rows:
        return definitions, inventory, None
    files = connection.execute(
        text("""
        SELECT f.game_display_name AS archive, f.name, f.size,
               lower(f.crc_hex) AS crc, lower(f.sha1_hex) AS sha1,
               split_part(f.tree_full_name, '/' || f.game_display_name || '/', 2) AS member,
               mapping.target_prefix || substr(f.tree_full_name, length(mapping.source_prefix)+1) AS full_path
        FROM staging.rv_files f
        LEFT JOIN LATERAL (
            SELECT source_prefix,target_prefix FROM ref.path_mapping m
            WHERE f.tree_full_name LIKE m.source_prefix || '/%'
            ORDER BY length(m.source_prefix) DESC LIMIT 1
        ) mapping ON true
        WHERE f.dat_root_full_name=:path
    """),
        {"path": rows[0]["dat_path"]},
    ).mappings()
    for file in files:
        value = dict(file)
        if value["full_path"]:
            value["path"] = value["full_path"].rsplit("/" + value["member"], 1)[0]
        else:
            value["path"] = None
        inventory[value["archive"].removesuffix(".zip")].append(value)
    return definitions, inventory, rows[0]["dat_sha256"]


def attach_samples(plan, definitions, inventory, dat_sha256):
    """Resolve only declared samples, retaining errors instead of guessing by name."""
    if not definitions:
        return plan
    result = deepcopy(plan)
    result["assets"] = [a for a in result["assets"] if a["kind"] != "sample"]
    remaining = []
    assets = {}
    for issue in result["missing"]:
        if issue["reason"] not in (
            "missing_sample_inventory",
            "missing_sample_definition",
        ):
            remaining.append(issue)
            continue
        owner = issue["sampleOf"]
        expected = next(
            (
                r
                for r in definitions.get(owner, {}).get("rom", [])
                if r["name"] == issue["name"] + ".wav" or r["name"] == issue["name"]
            ),
            None,
        )
        if expected is None:
            remaining.append(dict(issue, reason="missing_sample_definition"))
            continue
        match = next(
            (
                f
                for f in inventory[owner]
                if f["member"] == expected["name"]
                and f["size"] == int(expected["size"])
                and f["crc"] == expected.get("crc")
                and f["sha1"]
                and f["path"]
            ),
            None,
        )
        if match is None:
            remaining.append(dict(issue, reason="missing_inventory"))
            continue
        target = safe_path("fbneo/samples/" + owner + ".zip")
        asset = assets.setdefault(
            target,
            {
                "kind": "sample",
                "installRoot": "system",
                "installPath": target,
                "resolvedPath": match["path"],
                "requiredMembers": [],
            },
        )
        member = {key: match[key] for key in ("size", "sha1", "crc")}
        member["name"] = safe_path(match["member"])
        if member not in asset["requiredMembers"]:
            asset["requiredMembers"].append(member)
    result["assets"].extend(assets.values())
    result["missing"] = remaining
    result["complete"] = not remaining
    if assets:
        result["systemDirectory"] = "system"
        result["samplesDatSha256"] = dat_sha256
    return result


def refresh_sample_plans(engine, source_key):
    """Refresh dependency plans without rebuilding unrelated game identities."""
    from sqlalchemy import update

    from ..derive.schema import arcade_release as derived
    from .compatibility import CORES

    with engine.begin() as connection:
        definitions, inventory, sha256 = load_samples(connection, source_key)
        src = (
            connection.execute(select(source).where(source.c.source_key == source_key))
            .mappings()
            .one()
        )
        rows = (
            connection.execute(
                select(derived).where(derived.c.source_key == source_key)
            )
            .mappings()
            .all()
        )
        machine_definitions = {
            r.name: r
            for r in connection.execute(
                text(
                    "SELECT name, definition->'sample' AS sample, definition->>'sampleof' AS sampleof FROM staging.arcade_machine WHERE source_key=:key AND jsonb_array_length(definition->'sample')>0"
                ),
                {"key": source_key},
            )
        }
        changed = 0
        for row in rows:
            definition = machine_definitions.get(row["shortname"])
            if definition is None:
                continue
            old = row["plan"]
            # Repeat refresh starts from the source sample requirements, not previous resolution.
            plan = deepcopy(old)
            plan["missing"] = [m for m in plan["missing"] if m["kind"] != "sample"]
            plan["missing"].extend(
                {
                    "kind": "sample",
                    "owner": row["shortname"],
                    "name": s["name"],
                    "sampleOf": definition.sampleof or row["shortname"],
                    "reason": "missing_sample_inventory",
                }
                for s in definition.sample
            )
            plan = attach_samples(plan, definitions, inventory, sha256)
            if plan["complete"]:
                emulator = source_key.split(":")[0]
                plan["compatibleEmulators"] = [
                    {
                        "name": emulator,
                        "core": CORES[emulator],
                        "version": src["version"],
                        "sourceKey": source_key,
                        "datSha256": src["xml_sha256"],
                        "samplesDatSha256": sha256,
                        "validation": "dat_validated",
                    }
                ]
                plan["preferredCore"] = CORES[emulator]
            else:
                plan["compatibleEmulators"] = []
            connection.execute(
                update(derived)
                .where(
                    derived.c.dat_id == row["dat_id"],
                    derived.c.group_ordinal == row["group_ordinal"],
                )
                .values(plan=plan)
            )
            connection.execute(
                text(
                    "UPDATE catalog.arcade_release SET plan=CAST(:plan AS jsonb) WHERE install_signature=:signature"
                ),
                {"plan": json.dumps(plan), "signature": row["install_signature"]},
            )
            connection.execute(
                text(
                    "UPDATE derived.source_release SET needs_review=:review WHERE dat_id=:dat AND group_ordinal=:ordinal"
                ),
                {
                    "review": not plan["complete"],
                    "dat": row["dat_id"],
                    "ordinal": row["group_ordinal"],
                },
            )
            changed += 1
        connection.execute(
            text("""UPDATE catalog.release_fact f SET fact_value=CASE WHEN (a.plan->>'complete')::boolean THEN 'complete' ELSE 'incomplete' END
            FROM catalog.arcade_release a WHERE a.release_id=f.release_id AND a.source_key=:key AND f.fact_key='install_status' """),
            {"key": source_key},
        )
    return changed
