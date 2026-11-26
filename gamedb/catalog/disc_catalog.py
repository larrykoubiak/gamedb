"""Read verified Redump releases for the optical retail catalogs."""

from collections import defaultdict
from hashlib import sha256
import re

from sqlalchemy import text

from .software_identity import SOFTWARE_KEY_SQL


DISC_ADDON_PARENTS = {"segacd": "megadrive", "pcecd": "pcengine", "neogeocd": "neogeo"}
DISC_SYSTEMS = {
    "saturn": ("Sega", "Saturn"), "pcfx": ("NEC", "PC-FX"), "cd32": ("Commodore", "Amiga CD32"),
    "3do": ("The 3DO Company", "3DO Interactive Multiplayer"),
    "playdia": ("Bandai", "Playdia"), "pippin": ("Apple", "Pippin"), "cdi": ("Philips", "CD-i"),
    "segacd": ("Sega", "Mega-CD"), "pcecd": ("NEC", "PC Engine CD / TurboGrafx-CD"),
    "neogeocd": ("SNK", "Neo Geo CD"),
    "dreamcast": ("Sega", "Dreamcast"), "playstation2": ("Sony", "PlayStation 2"), "gamecube": ("Nintendo", "GameCube"),
}
NUMBERED_DISC = re.compile(r"\(Disc\s+(\d+|[A-D])(?:[ )-])", re.I)


ARCHIVES = text(f"""
    SELECT release.display_title AS title, signature.sha1_set_digest AS signature,
        software.id AS "softwareId", {SOFTWARE_KEY_SQL} AS "softwareKey",
        packages.names AS "archiveNames", packages.discs, facts.regions,
        facts.versions, facts.revisions, 'optical-disc' AS channel
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    JOIN catalog.software_release membership ON membership.software_id = software.id
    JOIN catalog.release release ON release.id = membership.release_id
    JOIN catalog.release_content_signature signature ON signature.release_id = release.id
    JOIN LATERAL (
        SELECT array_agg(package.archive_name ORDER BY part.media_sequence, package.archive_name) AS names,
            jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                'name', package.archive_name, 'number', part.media_sequence,
                'label', coalesce(nullif(part.media_description, ''), nullif(part.media_label, ''))
            )) ORDER BY part.media_sequence, package.archive_name) AS discs
        FROM catalog.release_package part
        JOIN catalog.package package ON package.id = part.package_id
        WHERE part.release_id = release.id
        HAVING count(*) > 0 AND bool_and(
            package.source_collection = :collection AND package.resolved_path IS NOT NULL
            AND (
                package.archive_name = ANY(CAST(:archive_names AS text[]))
                OR (CAST(:archive_names AS text[]) IS NULL AND
                    (CAST(:inferred_region AS text) IS NULL
                     OR package.resolved_path LIKE '%/Amiga CD32/Games/[ISO]/%'))
            )
            AND EXISTS (SELECT FROM catalog.package_file file WHERE file.package_id = package.id)
            AND NOT EXISTS (
                SELECT FROM catalog.package_file file
                WHERE file.package_id = package.id AND (NOT file.sha1_verified OR file.sha1_hex IS NULL)
            )
        )
        AND (release.expected_media_parts IS NULL
             OR (count(DISTINCT part.media_sequence) = release.expected_media_parts
                 AND min(part.media_sequence) = 1 AND max(part.media_sequence) = release.expected_media_parts))
    ) packages ON true
    JOIN LATERAL (
        SELECT coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value)
                   FILTER (WHERE fact_key = 'region' AND fact_value = ANY(CAST(:regions AS text[]))),
                   ARRAY[CAST(:inferred_region AS text)]) AS regions,
               coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value)
                   FILTER (WHERE fact_key = 'version'), '{{}}') AS versions,
               coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value)
                   FILTER (WHERE fact_key = 'revision'), '{{}}') AS revisions
        FROM catalog.release_fact
        WHERE release_id = release.id
        HAVING (bool_or(fact_key = 'region' AND fact_value = ANY(CAST(:regions AS text[])))
                OR (CAST(:inferred_region AS text) IS NOT NULL AND NOT bool_or(fact_key = 'region')
                    AND (CAST(:archive_names AS text[]) IS NOT NULL
                         OR bool_or(fact_key = 'dump_status' AND fact_value = 'verified'))))
            AND NOT bool_or(fact_key IN ('bios', 'demo', 'release_status', 'dump_modification')
                       OR (fact_key = 'dump_status' AND (fact_value <> 'verified' OR :collection <> 'TOSEC-ISO'))
                       OR (fact_key = 'license' AND fact_value = 'unlicensed'))
    ) facts ON true
    WHERE system.manufacturer_name = :manufacturer AND system.system_name = :system
        AND release.grouping_status <> 'media_ambiguous'
    ORDER BY release.display_title, packages.names, release.id
""")


def verified_disc_archives(connection, manufacturer, system, regions, collection, *,
                           inferred_region=None, archive_names=None):
    return [dict(row) for row in connection.execute(
        ARCHIVES, {"manufacturer": manufacturer, "system": system, "regions": sorted(regions),
                   "collection": collection, "inferred_region": inferred_region, "archive_names": archive_names},
    ).mappings()]


def redump_archives(connection, manufacturer, system, regions):
    return verified_disc_archives(connection, manufacturer, system, regions, "Redump")


def disc_bundle(title, entries, *, pressing=None, platform="saturn"):
    """Combine named, verified pressings in their published order."""
    components = [{"name": disc["name"], "signature": archive["signature"]}
                  for archive, disc in entries]
    names = [item["name"] for item in components]
    if not names or len(set(names)) != len(names):
        raise ValueError(f"A disc bundle requires distinct archive names: {title}")
    first = entries[0][0]
    token = "\0".join((f"gamedb:{platform}-disc-set", *(part["signature"] + ":" + part["name"] for part in components)))
    return {
        **first, "title": title, "signature": sha256(token.encode()).hexdigest()[:32],
        "archiveNames": names, "discs": [dict(disc, number=index) for index, (_, disc) in enumerate(entries, 1)],
        "components": components, "pressing": pressing, "revisions": [], "versions": [],
    }


def complete_disc_archives(platform, archives, reviews, *, standalone=()):
    """Keep complete pressings and join explicitly named multi-disc editions."""
    individual = defaultdict(list)
    for archive in archives:
        if len(archive["discs"]) == 1:
            (disc,) = archive["discs"]
            name = disc["name"]
            individual[name].append((archive, disc))
            if name not in standalone and (disc.get("number") is not None or NUMBERED_DISC.search(name)):
                continue
        yield archive
    for review in reviews:
        candidates = [individual[name] for name in review["archives"]]
        if all(len(group) == 1 for group in candidates):
            entries = [group[0] for group in candidates]
            if len({tuple(archive["regions"]) for archive, _ in entries}) != 1:
                raise ValueError(f"Disc regions disagree for {review['title']!r}")
            yield {**disc_bundle(review["title"], entries, platform=platform), "evidence": review["source"]}


def approved_disc_matches(archives, reviews):
    by_name = defaultdict(list)
    for archive in archives:
        by_name[tuple(archive["archiveNames"])].append(archive)
    for review in reviews:
        signature = review.get("signature")
        matches = [archive for archive in by_name[tuple(review["archives"])]
                   if signature is None or archive["signature"] == signature]
        if len(matches) == 1:
            yield {"edition": review["edition"], "market": review["market"], "signature": matches[0]["signature"],
                   "evidence": review["source"]}


def addon_disc_archives(connection, platform, markets, reference):
    regions = set().union(*markets.values(), {"WORLD"})
    raw = redump_archives(connection, *DISC_SYSTEMS[platform], regions)
    for archive in complete_disc_archives(
        platform, raw, reference.get("discSets", ()), standalone=reference.get("standaloneDiscs", ()),
    ):
        if platform == "segacd" and any(re.search(r"\([^()]*\b32X\b[^()]*\)", name, re.I)
                                       for name in archive["archiveNames"]):
            archive = dict(archive, channel="32x-cd")
        yield archive
