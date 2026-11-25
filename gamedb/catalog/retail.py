"""Match and publish retail catalogs against GameDB inventory."""

from collections import Counter, defaultdict
import csv
from itertools import product
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata

from sqlalchemy import text

from gamedb.catalog.retail_source import known_credit
from gamedb.catalog.software_identity import SOFTWARE_KEY_SQL
from gamedb.launchbox.matching import title_key


RETAIL_PLATFORMS = {"snes": "SNES", "megadrive": "Mega Drive", "nes": "NES / Famicom",
                    "playstation": "PlayStation (US)", "neogeo": "Neo Geo", "mastersystem": "Master System"}
ARCHIVE_MARKETS = {
    "JP": {"JP"},
    "NA": {"US", "CA", "MX"},
    "PAL": {"EU", "AU", "NZ", "GB", "DE", "FR", "ES", "IT", "NL", "SE", "SCANDINAVIA"},
}
LONG_VOWELS = {"ā": ("a", "aa"), "ē": ("e", "ee", "ei"), "ī": ("i", "ii"),
               "ō": ("o", "ou", "oo"), "ū": ("u", "uu")}

def base_archives_query(manufacturer=":manufacturer", commercial_labels=":commercial_labels"):
    return text(f"""
    SELECT release.display_title AS title, signature.sha1_set_digest AS signature,
           software.id AS "softwareId", {SOFTWARE_KEY_SQL} AS "softwareKey",
           packages.names AS "archiveNames", facts.regions,
           facts.versions, facts.revisions,
           CASE WHEN system.system_name = :sufami THEN 'sufami-turbo'
                WHEN facts.nintendo_power THEN 'nintendo-power'
                ELSE 'cartridge' END AS channel
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    JOIN catalog.software_release membership ON membership.software_id = software.id
    JOIN catalog.release release ON release.id = membership.release_id
    JOIN catalog.release_content_signature signature ON signature.release_id = release.id
    JOIN LATERAL (
        SELECT array_agg(package.archive_name ORDER BY package.archive_name) AS names
        FROM catalog.release_package member
        JOIN catalog.package package ON package.id = member.package_id
        WHERE member.release_id = release.id
        HAVING count(*) > 0 AND bool_and(
            package.source_collection = 'No-Intro' AND package.resolved_path IS NOT NULL
            AND NOT EXISTS (
                SELECT FROM derived.tag_classification tag
                WHERE tag.archive_name_id = member.source_archive_name_id
                  AND tag.record_index = member.source_record_index
                  AND tag.classification_status <> 'classified'
                  AND (CAST(:verified_labels AS jsonb) ->> signature.sha1_set_digest)
                      IS DISTINCT FROM package.archive_name
            )
            AND NOT EXISTS (
                SELECT FROM catalog.package_file file
                WHERE file.package_id = package.id AND NOT file.sha1_verified
            )
        )
    ) packages ON true
    JOIN LATERAL (
        SELECT
            coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value)
                FILTER (WHERE fact_key = 'region'), '{{}}') AS regions,
            coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value)
                FILTER (WHERE fact_key = 'version'), '{{}}') AS versions,
            coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value)
                FILTER (WHERE fact_key = 'revision'), '{{}}') AS revisions,
            bool_or(fact_key = 'special' AND fact_value = 'NP') AS nintendo_power
        FROM catalog.release_fact fact
        WHERE fact.release_id = release.id
        HAVING NOT bool_or(
            fact_key IN ('bios', 'demo', 'release_status', 'dump_status',
                         'dump_modification', 'distribution_channel')
            OR (fact_key = 'license' AND fact_value = 'unlicensed'
                AND packages.names IS DISTINCT FROM
                    ARRAY[CAST({commercial_labels} AS jsonb) ->> signature.sha1_set_digest])
        )
    ) facts ON true
    WHERE system.manufacturer_name = {manufacturer}
      AND system.system_name IN (:system, :sufami)
    ORDER BY release.display_title, packages.names, release.id
""")


BASE_ARCHIVES = base_archives_query()

PUBLICATION_SCHEMA = """
    CREATE SCHEMA IF NOT EXISTS app;
    CREATE TABLE IF NOT EXISTS {catalog} (
        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
        published_at timestamptz NOT NULL DEFAULT current_timestamp,
        payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
    );
    CREATE TABLE IF NOT EXISTS {image} (
        path text PRIMARY KEY,
        filename text NOT NULL,
        crc32 bigint
    );
    CREATE TABLE IF NOT EXISTS {soundtrack} (
        soundtrack_key text PRIMARY KEY
    );
"""


def retail_tables(platform):
    if platform not in RETAIL_PLATFORMS:
        raise ValueError(f"Unknown retail platform {platform!r}")
    return tuple(f"app.{platform}_retail_{part}" for part in ("catalog", "image", "soundtrack"))


def read_archives(connection, manufacturer, system, verified_archives=(), *, secondary_system=None):
    verified_labels = {record["signature"]: record["archiveName"] for record in verified_archives
                       if "archiveName" in record}
    commercial_labels = {record["signature"]: record["archiveName"] for record in verified_archives
                         if record.get("independentRetail")}
    return [dict(row) for row in connection.execute(
        BASE_ARCHIVES, {"manufacturer": manufacturer, "system": system, "sufami": secondary_system,
                        "verified_labels": json.dumps(verified_labels), "commercial_labels": json.dumps(commercial_labels)},
    ).mappings()]


def _title_key(name):
    name = re.sub(r"(?<=\d)×(?=\d)", "x", name)
    name = re.sub(r"^(.+?),\s*(the|an|a)(?=\s+-\s+|:)", r"\2 \1", name, flags=re.IGNORECASE)
    return title_key(name)


def _compact_title(name):
    return "".join(char for char in unicodedata.normalize("NFD", _title_key(name)) if char.isalnum())


def _spelling_keys(name):
    """Expand only explicit long vowels in the published spelling."""
    letters = _title_key(name).replace(" ", "")
    options = [LONG_VOWELS[char] if char in LONG_VOWELS else (_compact_title(char),) for char in letters]
    return {"".join(parts) for parts in product(*options)}


def read_aliases(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def match_archives(catalog, archives, reviewed_aliases, verified_archives=(), *, markets=ARCHIVE_MARKETS):
    """Match title spellings and markets and surface overlapping claims for review."""
    releases = [release for game in catalog["games"] for release in game["releases"]]
    by_edition = {(release["edition"], release["market"]): release for release in releases}
    reviewed = defaultdict(dict)
    for alias in reviewed_aliases:
        release = by_edition.get((alias["edition"], alias["market"]))
        key = _title_key(alias["archiveTitle"])
        if release is None or not key or key in reviewed[release["key"]]:
            raise ValueError(f"Invalid retail archive alias {alias!r}")
        reviewed[release["key"]][key] = alias.get("evidence", "")
    verified = defaultdict(dict)
    for item in verified_archives:
        release = by_edition.get((item["edition"], item["market"]))
        signature = item["signature"]
        if (release is None or not re.fullmatch(r"[0-9a-f]{32}", signature)
                or not item["evidence"] or signature in verified[release["key"]]):
            raise ValueError(f"Invalid retail archive verification {item!r}")
        verified[release["key"]][signature] = item["evidence"]

    index = defaultdict(list)
    spellings = defaultdict(list)
    contents = defaultdict(list)
    independent = {item["signature"] for item in verified_archives if item.get("independentRetail")}
    for archive in archives:
        regions = set(archive["regions"])
        channel = archive["channel"]
        for market, countries in markets.items():
            if regions.intersection(countries) or ("WORLD" in regions and market in ARCHIVE_MARKETS):
                if archive["signature"] not in independent:
                    index[market, channel, _title_key(archive["title"])].append(archive)
                    spellings[market, channel, _compact_title(archive["title"])].append(archive)
                contents[market, channel, archive["signature"]].append(archive)

    claims = defaultdict(set)
    direct_claims = defaultdict(set)
    candidates = {}
    for release in releases:
        scope = release["market"], release["channel"]
        title_keys = {_title_key(title) for title in release["titles"]}
        aliases = reviewed[release["key"]]
        approved = verified[release["key"]]
        matches = []
        if approved:
            matches = [{**archive, "basis": "reviewed-content-and-region", "evidence": evidence}
                       for signature, evidence in approved.items() for archive in contents[(*scope, signature)]]
        else:
            for key in title_keys | aliases.keys():
                basis = "title-and-region" if key in title_keys else "reviewed-alias-and-region"
                for archive in index[(*scope, key)]:
                    matches.append({**archive, "basis": basis, "evidence": aliases.get(key)})
        for archive in matches:
            direct_claims[archive["signature"]].add(release["edition"])
        if not matches and not approved:
            spelling_keys = set().union(*(_spelling_keys(name) for name in release["titles"]))
            matches = [{**archive, "basis": "spelling-and-region"}
                       for key in spelling_keys for archive in spellings[(*scope, key)]]
        for archive in matches:
            claims[archive["signature"]].add(release["edition"])
        candidates[release["key"]] = sorted(matches, key=lambda item: (item["archiveNames"], item["signature"]))

    for release in releases:
        release.pop("archives", None)
        release.pop("candidates", None)
        matches = candidates[release["key"]]
        approved = verified[release["key"]]
        owners = claims if matches and matches[0]["basis"] == "spelling-and-region" else direct_claims
        overlapping = any(len(owners[match["signature"]]) > 1 for match in matches)
        same_software = len({match["softwareKey"] for match in matches}) == 1
        if matches and (same_software or approved) and not overlapping:
            release.update(status="matched", archives=matches)
        elif matches:
            release.update(status="ambiguous", candidates=matches)
        else:
            release.update(status="unmatched")
    summarize_matches(catalog, len(archives), markets)
    return catalog


def summarize_matches(catalog, archive_count, markets):
    releases = [release for game in catalog["games"] for release in game["releases"]]
    counts = Counter()
    by_market = {market: Counter() for market in markets}
    for release in releases:
        counts[release["status"]] += 1
        by_market[release["market"]][release["status"]] += 1

    def coverage(counter):
        return {status: counter[status] for status in ("matched", "ambiguous", "unmatched")}

    catalog["summary"] = {
        "games": len(catalog["games"]),
        "gamesWithMatches": sum(any(release["status"] == "matched" for release in game["releases"])
                                for game in catalog["games"]),
        "releases": len(releases),
        **coverage(counts),
        "byMarket": {market: coverage(counter) for market, counter in by_market.items()},
        "eligibleArchives": archive_count,
    }


def cartridge_group_matches(catalog, archives, fingerprints, records, *, markets=ARCHIVE_MARKETS):
    """Use hardware-source clone groups that identify one documented edition."""
    by_digest, by_name, by_group = defaultdict(list), defaultdict(set), defaultdict(list)
    for record in records:
        by_digest[record.digest].append(record)
        for name in record.names:
            by_name[_compact_title(name)].add(record.group)
    for archive in archives:
        for record in by_digest[fingerprints.get(archive["signature"])]:
            by_group[record.group].append((archive, record))

    releases = [release for game in catalog["games"] for release in game["releases"]]
    owners, wanted, seen = defaultdict(set), {}, {}
    for release in releases:
        edition = release["edition"]
        anchors = set()
        for archive in release.get("archives", ()):
            signature = archive["signature"]
            seen[signature] = edition
            anchors.update(record.group for record in by_digest[fingerprints.get(signature)])
        groups = anchors or set().union(*(by_name[_compact_title(name)] for name in (*release["titles"], edition)))
        wanted[release["key"]] = groups
        for group in groups:
            owners[group].add(edition)

    for release in releases:
        if release["status"] != "unmatched":
            continue
        edition, market = release["edition"], release["market"]
        groups = {group for group in wanted[release["key"]] if owners[group] == {edition}}
        if len(groups) != 1:
            continue
        (group,) = groups
        verified = {}
        for archive, record in by_group[group]:
            signature = archive["signature"]
            territories = set(archive["regions"])
            if seen.get(signature, edition) != edition:
                continue
            if territories & markets[market] or ("WORLD" in territories and market in record.markets):
                source = record.evidence["source"]
                verified[signature] = f"{source['url']} ({source['record']}, cartridge SHA-1)"
        for signature, evidence in sorted(verified.items()):
            yield {"edition": edition, "market": market, "signature": signature, "evidence": evidence}


def publish(connection, catalog, platform):
    catalog_table, image_table, soundtrack_table = retail_tables(platform)
    connection.exec_driver_sql(PUBLICATION_SCHEMA.format(
        catalog=catalog_table, image=image_table, soundtrack=soundtrack_table,
    ))
    images = {
        asset["path"]: {field: asset[field] for field in ("path", "filename", "crc32")}
        for game in catalog["games"] for release in game["releases"]
        for asset in release.get("artwork", {}).values() if "path" in asset
    }
    connection.exec_driver_sql(f"DELETE FROM {image_table}")
    connection.execute(text(f"""
        INSERT INTO {image_table} (path, filename, crc32)
        SELECT path, filename, crc32
        FROM jsonb_to_recordset(CAST(:images AS jsonb)) AS image(path text, filename text, crc32 bigint)
    """), {"images": json.dumps(list(images.values()))})
    soundtrack_keys = sorted({link["key"] for game in catalog["games"]
                              for link in game.get("soundtrackLinks", ())})
    connection.exec_driver_sql(f"DELETE FROM {soundtrack_table}")
    connection.execute(text(f"""
        INSERT INTO {soundtrack_table} (soundtrack_key)
        SELECT jsonb_array_elements_text(CAST(:keys AS jsonb))
    """), {"keys": json.dumps(soundtrack_keys)})
    connection.execute(text(f"""
        INSERT INTO {catalog_table} (singleton, payload)
        VALUES (true, CAST(:payload AS jsonb))
        ON CONFLICT (singleton) DO UPDATE
        SET payload = excluded.payload, published_at = current_timestamp
    """), {"payload": json.dumps(catalog, ensure_ascii=False)})


def write_report(path, catalog):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(catalog, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def enrichment_coverage(catalog, markets=ARCHIVE_MARKETS):
    counts = {market: Counter() for market in markets}
    for game in catalog["games"]:
        for release in game["releases"]:
            bucket = counts[release["market"]]
            records = [*release.get("cartridgeScans", ()), *(record
                       for archive in release.get("archives", ()) for record in archive.get("cartridge", ()))]
            bucket.update({
                "serial": int(bool(release.get("productCodes")) or any(record.get("serials") for record in records)),
                "pcb": int(any(record.get("boards") for record in records)),
                "boxart": int("boxart" in release.get("artwork", {})),
                "titleScreen": int("title" in release.get("artwork", {})),
                "gameplay": int("snap" in release.get("artwork", {})),
                "logo": int("logo" in release.get("artwork", {})),
                "manual": int(bool(release.get("manuals"))),
            })
    return {
        "descriptions": sum(bool(game.get("description")) for game in catalog["games"]),
        "developers": sum(known_credit(game["developer"]) for game in catalog["games"]),
        "publishers": sum(known_credit(game["publisher"]) for game in catalog["games"]),
        "releases": {field: sum(bucket[field] for bucket in counts.values())
                     for field in ("serial", "pcb", "boxart", "titleScreen", "gameplay", "logo", "manual")},
        "byMarket": {market: dict(bucket) for market, bucket in counts.items()},
    }
