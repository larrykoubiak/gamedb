"""Exact normalized title candidates inside explicitly mapped platforms only."""
from collections import defaultdict
import csv
import re
import unicodedata

FACT_FIELDS = {
    "description": "Overview", "developer": "Developer", "publisher": "Publisher",
    "genre": "Genres", "franchise": "Series", "player_count": "MaxPlayers",
}
MATCHER_VERSION = "platform-title-evidence-v2"


def title_key(value):
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    # DAT names commonly move English articles to the end.
    match = re.fullmatch(r"(.+),\s*(the|an|a)", value)
    if match:
        value = f"{match[2]} {match[1]}"
    # Keep accents, numbers and qualifier words. No fuzzy/substring matching.
    return " ".join("".join(c if c.isalnum() else " " for c in value).split())


def read_platform_map(path):
    mapping = defaultdict(set)
    with open(path, newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = (row["canonical_manufacturer_name"], row["canonical_system_name"])
            platform = row["launchbox_platform"]
            if not all((*key, platform)):
                raise ValueError("platform mapping contains a blank identity")
            mapping[key].add(platform)
    return dict(mapping)


def match_candidates(software, games, aliases, platform_map):
    index = defaultdict(set)
    for game_id, game in games.items():
        for name in [game["Name"], *aliases.get(game_id, ())]:
            key = title_key(name)
            if key:
                index[(game["Platform"], key)].add(game_id)
    candidates = {}
    owners = defaultdict(set)
    for item in software:
        system = (item["manufacturer_name"], item["system_name"])
        hits = set()
        for platform in platform_map.get(system, ()):
            for name in item["titles"]:
                hits.update(index.get((platform, title_key(name)), ()))
        candidates[item["id"]] = hits
        for game_id in hits:
            # Catalog software is platform-specific; ambiguity is checked within
            # that same system, including claimants with multiple candidates.
            owners[(system, game_id)].add(item["id"])
    results = []
    for item in software:
        system = (item["manufacturer_name"], item["system_name"])
        hits = candidates[item["id"]]
        if system not in platform_map:
            status = "unmapped_platform"
        elif not hits:
            status = "unmatched"
        elif len(hits) > 1:
            status = "ambiguous_source"
        elif len(owners[(system, next(iter(hits)))]) > 1:
            status = "ambiguous_catalog"
        else:
            status = "unique"
        result = {"software_id": item["id"], "status": status, "database_ids": sorted(hits),
                  "initial_status": status, "selected_database_id": None,
                  "resolution_basis": []}
        if status == "unique":
            result["selected_database_id"] = next(iter(hits))
        elif status.startswith("ambiguous"):
            selected, evidence = resolve_candidates(item, hits, games)
            if selected is not None:
                result["status"] = "resolved_shared" if len(owners[(system, selected)]) > 1 else "resolved_source"
                result["selected_database_id"] = selected
                result["resolution_basis"] = evidence
        results.append(result)
    return results


def literal_title_key(value):
    """A stronger title comparison: preserve punctuation and edition symbols."""
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = value.translate(str.maketrans({"’": "'", "‘": "'", "–": "-", "—": "-"}))
    match = re.fullmatch(r"(.+),\s*(the|an|a)", value)
    if match:
        value = f"{match[2]} {match[1]}"
    return " ".join(value.split())


def resolve_candidates(item, hits, games):
    """Resolve enrichment links only; never merge catalog software identities.

    Require corroboration beyond title. Prefer a literal primary name only when
    supported by a date or company. Alias-only matches need both date and company.
    Missing evidence never counts as a mismatch; tied candidates stay unresolved.
    """
    facts = item.get("match_facts", {})
    years = {v[:4] for v in facts.get("release_date", ()) if re.match(r"^\d{4}(?:$|[-/])", v)}
    # Company spelling is normalized conservatively: no substring matching or
    # guessed company equivalences (e.g. Rareware -> Rare).
    companies = {title_key(v) for k in ("developer", "publisher") for v in facts.get(k, ()) if title_key(v)}
    literal_names = {literal_title_key(v) for v in item["titles"]}
    supported = []
    for game_id in hits:
        game = games[game_id]
        year = (game.get("ReleaseDate") or game.get("ReleaseYear") or "")[:4]
        year_match = bool(year and year in years)
        company_match = any(title_key(game.get(k, "")) in companies for k in ("Developer", "Publisher") if game.get(k))
        if companies and (game.get("Developer") or game.get("Publisher")) and not company_match:
            continue
        primary = literal_title_key(game["Name"]) in literal_names
        # Multiple explicit source years may describe rereleases. They cannot
        # supply date corroboration for automatic disambiguation.
        year_match = year_match and len(years) == 1
        if not ((primary and (year_match or company_match)) or (year_match and company_match)):
            continue
        # A known contradictory year makes a decision review-only. Regional
        # launch dates can differ, so this does not reject the raw candidate.
        if years and year and year not in years:
            continue
        evidence = []
        if primary:
            evidence.append("literal_primary_title")
        if year_match:
            evidence.append("release_year")
        if company_match:
            evidence.append("company")
        supported.append(((int(primary), int(year_match) + int(company_match)), game_id, evidence))
    if not supported:
        return None, []
    best = max(row[0] for row in supported)
    winners = [row for row in supported if row[0] == best]
    if len(winners) != 1:
        return None, []
    return winners[0][1], winners[0][2]
