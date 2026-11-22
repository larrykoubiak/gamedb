"""Match documented SNES releases to original cartridge inventory and publish the result."""

from collections import Counter, defaultdict
import csv
from itertools import product
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata

from sqlalchemy import text

from gamedb.catalog.snes_cartridges import add_cartridge_evidence, cartridge_hashes, read_cartridge_roms
from gamedb.catalog.snes_media import add_descriptions_and_art, add_manuals
from gamedb.catalog.snes_references import GAMING_ALEXANDRIA, SourceIndex, reference_indexes, snes_central_indexes
from gamedb.catalog.snes_source import known_credit, load_html, parse_retail_list
from gamedb.catalog.snes_soundtracks import add_soundtracks
from gamedb.catalog.software_identity import SOFTWARE_KEY_SQL
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.launchbox.matching import title_key


SYSTEM_NAME = "Super Nintendo Entertainment System"
SUFAMI_SYSTEM = "Sufami Turbo"
ARCHIVE_MARKETS = {
    "JP": {"JP"},
    "NA": {"US", "CA", "MX"},
    "PAL": {"EU", "AU", "NZ", "GB", "DE", "FR", "ES", "IT", "NL", "SE", "SCANDINAVIA"},
}
LONG_VOWELS = {"ā": ("a", "aa"), "ē": ("e", "ee", "ei"), "ī": ("i", "ii"),
               "ō": ("o", "ou", "oo"), "ū": ("u", "uu")}

BASE_ARCHIVES = text(f"""
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
            OR (fact_key = 'license' AND fact_value = 'unlicensed')
        )
    ) facts ON true
    WHERE system.manufacturer_name = 'Nintendo' AND system.system_name IN (:system, :sufami)
    ORDER BY release.display_title, packages.names, release.id
""")

PUBLICATION_SCHEMA = """
    CREATE SCHEMA IF NOT EXISTS app;
    CREATE TABLE IF NOT EXISTS app.snes_retail_catalog (
        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
        published_at timestamptz NOT NULL DEFAULT current_timestamp,
        payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
    );
    CREATE TABLE IF NOT EXISTS app.snes_retail_image (
        path text PRIMARY KEY,
        filename text NOT NULL,
        crc32 bigint
    );
    CREATE TABLE IF NOT EXISTS app.snes_retail_soundtrack (
        soundtrack_key text PRIMARY KEY
    );
"""


def read_archives(connection, verified_archives=()):
    verified_labels = {record["signature"]: record["archiveName"] for record in verified_archives
                       if "archiveName" in record}
    return [dict(row) for row in connection.execute(
        BASE_ARCHIVES, {"system": SYSTEM_NAME, "sufami": SUFAMI_SYSTEM,
                        "verified_labels": json.dumps(verified_labels)},
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


def match_archives(catalog, archives, reviewed_aliases, verified_archives=()):
    """Match title spellings and markets and surface overlapping claims for review."""
    releases = [release for game in catalog["games"] for release in game["releases"]]
    by_edition = {(release["edition"], release["market"]): release for release in releases}
    reviewed = defaultdict(dict)
    for alias in reviewed_aliases:
        release = by_edition.get((alias["edition"], alias["market"]))
        key = _title_key(alias["archiveTitle"])
        if release is None or not key or key in reviewed[release["key"]]:
            raise ValueError(f"Invalid SNES retail archive alias {alias!r}")
        reviewed[release["key"]][key] = alias.get("evidence", "")
    verified = defaultdict(dict)
    for item in verified_archives:
        release = by_edition.get((item["edition"], item["market"]))
        signature = item["signature"]
        if (release is None or not re.fullmatch(r"[0-9a-f]{32}", signature)
                or not item["evidence"] or signature in verified[release["key"]]):
            raise ValueError(f"Invalid SNES retail archive verification {item!r}")
        verified[release["key"]][signature] = item["evidence"]

    index = defaultdict(list)
    spellings = defaultdict(list)
    contents = defaultdict(list)
    for archive in archives:
        regions = set(archive["regions"])
        channel = archive["channel"]
        for market, countries in ARCHIVE_MARKETS.items():
            if regions.intersection(countries) or "WORLD" in regions:
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

    counts = Counter()
    markets = {market: Counter() for market in ARCHIVE_MARKETS}
    for release in releases:
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
        counts[release["status"]] += 1
        markets[release["market"]][release["status"]] += 1

    def coverage(counter):
        return {status: counter[status] for status in ("matched", "ambiguous", "unmatched")}

    catalog["summary"] = {
        "games": len(catalog["games"]),
        "gamesWithMatches": sum(any(release["status"] == "matched" for release in game["releases"])
                                for game in catalog["games"]),
        "releases": len(releases),
        **coverage(counts),
        "byMarket": {market: coverage(counter) for market, counter in markets.items()},
        "eligibleArchives": len(archives),
    }
    return catalog


def publish(connection, catalog):
    connection.exec_driver_sql(PUBLICATION_SCHEMA)
    images = {
        asset["path"]: {field: asset[field] for field in ("path", "filename", "crc32")}
        for game in catalog["games"] for release in game["releases"]
        for asset in release.get("artwork", {}).values() if "path" in asset
    }
    connection.exec_driver_sql("DELETE FROM app.snes_retail_image")
    connection.execute(text("""
        INSERT INTO app.snes_retail_image (path, filename, crc32)
        SELECT path, filename, crc32
        FROM jsonb_to_recordset(CAST(:images AS jsonb)) AS image(path text, filename text, crc32 bigint)
    """), {"images": json.dumps(list(images.values()))})
    soundtrack_keys = sorted({link["key"] for game in catalog["games"]
                              for link in game.get("soundtrackLinks", ())})
    connection.exec_driver_sql("DELETE FROM app.snes_retail_soundtrack")
    connection.execute(text("""
        INSERT INTO app.snes_retail_soundtrack (soundtrack_key)
        SELECT jsonb_array_elements_text(CAST(:keys AS jsonb))
    """), {"keys": json.dumps(soundtrack_keys)})
    connection.execute(text("""
        INSERT INTO app.snes_retail_catalog (singleton, payload)
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


def enrichment_coverage(catalog):
    counts = {market: Counter() for market in ARCHIVE_MARKETS}
    for game in catalog["games"]:
        for release in game["releases"]:
            bucket = counts[release["market"]]
            records = [*release.get("cartridgeScans", ()), *(record
                       for archive in release.get("archives", ()) for record in archive.get("cartridge", ()))]
            bucket.update({
                "serial": int(any(record.get("serials") for record in records)),
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


def seed_snes(html_path=None, report=None, *, publish_catalog=False, sources=None, hash_cartridges=False):
    directory = PROJECT_ROOT / "reference"
    reference = json.loads((directory / "snes_retail.json").read_text(encoding="utf-8"))
    reviewed = read_aliases(directory / "snes_retail_aliases.csv")
    verified = reference["verifiedArchives"]
    catalog = parse_retail_list(load_html(html_path), reference["editions"], release_notes=reference["releaseNotes"])
    sources = sources or PROJECT_ROOT / "data/media/cache/snes-retail"
    indexes, warnings = reference_indexes(sources)
    indexes["ga-sfc-references.json"] = SourceIndex(
        GAMING_ALEXANDRIA, (directory / "snes_retail_japanese_manuals.json").read_bytes(),
    )
    central = list(snes_central_indexes(sources))
    catalog["enrichmentSources"] = [
        {"url": index.url, "sha256": index.digest} for index in (*indexes.values(), *(index for _, index in central))
    ]
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('gamedb.snes-retail'))")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            match_archives(catalog, read_archives(connection, verified), reviewed, verified)
            roms = read_cartridge_roms(connection, catalog)
            fingerprint_path = sources / "cartridge-sha256.json"
            fingerprints = cartridge_hashes(fingerprint_path, roms, hash_cartridges)
            if hash_cartridges:
                write_report(fingerprint_path, fingerprints)
                missing = len({rom.sha1 for rom in roms.values()} - fingerprints.keys())
                if missing:
                    warnings.append(f"{missing} cartridge ROMs could not be fingerprinted from local ZIPs")
            add_cartridge_evidence(connection, catalog, roms, fingerprints, indexes, central, reference)
            add_descriptions_and_art(connection, catalog, indexes, reference)
            add_manuals(catalog, indexes, reference.get("manualAliases", ()), reference.get("manuals", ()))
            catalog["summary"]["metadata"] = enrichment_coverage(catalog)
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, read_aliases(directory / "snes_retail_soundtrack_aliases.csv"),
            )
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            if publish_catalog:
                publish(connection, catalog)
    finally:
        engine.dispose()
    if report is not None:
        write_report(report, catalog)
    return {"revision": catalog["source"]["revision"], "published": publish_catalog, **catalog["summary"]}
