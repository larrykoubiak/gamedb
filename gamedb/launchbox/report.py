"""Read one catalog/snapshot consistently and write an auditable coverage report."""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from sqlalchemy import text

from .inputs import load_inputs
from .importer import sha256_file
from .matching import FACT_FIELDS, MATCHER_VERSION, match_candidates, read_platform_map


def write_report(engine, directory, platform_map_path, revision=None):
    directory = Path(directory)
    # A report directory is immutable: reruns must choose a new destination.
    if directory.exists():
        raise ValueError(f"report directory already exists: {directory}")
    platforms = read_platform_map(platform_map_path)
    mapping_revision = sha256_file(platform_map_path)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        c.execute(text("SET TRANSACTION READ ONLY"))
        snapshot, games, aliases, software, existing = load_inputs(c, revision)
    known_platforms = {g["Platform"] for g in games.values()}
    unknown_platforms = sorted({p for values in platforms.values() for p in values} - known_platforms)
    if unknown_platforms:
        raise ValueError(f"mapped platforms absent from snapshot games: {unknown_platforms}")
    by_id = {item["id"]: item for item in software}
    results = match_candidates(software, games, aliases, platforms)
    counts = Counter()
    fields_available = Counter()
    fields_missing = Counter()
    per_system = defaultdict(Counter)
    unique_games = set()
    directory.mkdir(parents=True)
    with (directory / "matches.csv").open("w", newline="", encoding="utf-8") as stream:
        columns = ["software_id", "manufacturer", "system", "title", "identity_basis", "catalog_titles", "status", "launchbox_ids", "launchbox_names", "missing_fact_keys", "initial_status", "selected_launchbox_id", "resolution_basis", "match_facts"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for result in results:
            item = by_id[result["software_id"]]
            status = result["status"]
            counts[status] += 1
            per_system[(item["manufacturer_name"], item["system_name"])][status] += 1
            missing = []
            if result["selected_database_id"] is not None:
                game_id = result["selected_database_id"]
                unique_games.add(game_id)
                game = games[game_id]
                for key, source in FACT_FIELDS.items():
                    if game.get(source, "").strip():
                        fields_available[key] += 1
                        if key not in existing[item["id"]]:
                            fields_missing[key] += 1
                            missing.append(key)
            writer.writerow(dict(
                software_id=item["id"], manufacturer=item["manufacturer_name"],
                system=item["system_name"], title=item["display_name"],
                identity_basis=item["identity_basis"], status=status,
                catalog_titles=json.dumps(sorted(item["titles"]), ensure_ascii=False),
                launchbox_ids=json.dumps(result["database_ids"]),
                launchbox_names=json.dumps([games[x]["Name"] for x in result["database_ids"]], ensure_ascii=False),
                missing_fact_keys=json.dumps(missing),
                initial_status=result["initial_status"],
                selected_launchbox_id=result["selected_database_id"],
                resolution_basis=json.dumps(result["resolution_basis"]),
                match_facts=json.dumps({k: sorted(v) for k, v in item["match_facts"].items()}, ensure_ascii=False),
            ))
    with (directory / "matched_games.jsonl").open("w", encoding="utf-8") as stream:
        for game_id in sorted(unique_games):
            stream.write(json.dumps({"game": games[game_id],
                                     "alternate_names": sorted(aliases.get(game_id, ()))},
                                    ensure_ascii=False) + "\n")
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": snapshot["source_revision"],
        "source_url": snapshot["source_url"], "source_games": len(games),
        "source_alternate_names": sum(map(len, aliases.values())),
        "matcher_version": MATCHER_VERSION,
        "platform_map_sha256": mapping_revision,
        "catalog_software": len(software), "status_counts": dict(counts),
        "available_facts_on_selected_matches": dict(fields_available),
        "missing_facts_on_selected_matches": dict(fields_missing),
        "systems": [{"manufacturer": m, "system": s, **dict(counts)}
                    for (m, s), counts in sorted(per_system.items())],
        "notes": [
            "Candidate report only: no metadata or identity changes were applied.",
            "Unique means one candidate in both directions within a canonical system, not proof of identity.",
            "Resolved links use title plus date/company corroboration; shared links do not merge catalog identities.",
            "Software IDs belong to this catalog build; rerun after rebuilding.",
            "Normalization retains accents, numbers and qualifiers; fuzzy matching is disabled.",
        ],
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {key: value for key, value in summary.items() if key != "systems"}
