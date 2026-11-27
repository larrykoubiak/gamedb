"""Link installable prepatched images to the retail release they modify."""

from collections import defaultdict

from sqlalchemy import text

from .retail import _title_key


VARIANTS = text("""
    SELECT release.display_title AS title, software.id AS software_id,
           signature.sha1_set_digest AS signature, packages.names, facts.regions, facts.version,
           facts.modification
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN catalog.software_release membership ON membership.software_id = software.id
    JOIN catalog.release release ON release.id = membership.release_id
    JOIN catalog.release_content_signature signature ON signature.release_id = release.id
    JOIN LATERAL (
        SELECT array_agg(package.archive_name ORDER BY part.media_sequence, package.archive_name) AS names
        FROM catalog.release_package part
        JOIN catalog.package package ON package.id = part.package_id
        WHERE part.release_id = release.id
        HAVING count(*) > 0
            AND bool_and(package.source_collection IN ('Integrated', 'English Translations')
                         AND package.resolved_path IS NOT NULL)
            AND (release.expected_media_parts IS NULL OR
                 count(DISTINCT part.media_sequence) = release.expected_media_parts)
    ) packages ON true
    JOIN LATERAL (
        SELECT array_agg(DISTINCT fact_value) FILTER (WHERE fact_key = 'region') AS regions,
               min(fact_value) FILTER (WHERE fact_key = 'version') AS version,
               min(fact_value) FILTER (WHERE fact_key = 'dump_modification') AS modification
        FROM catalog.release_fact
        WHERE release_id = release.id
    ) facts ON facts.modification IN ('undub', 'translated')
    WHERE system.manufacturer_name = :manufacturer AND system.system_name = :system
      AND release.grouping_status <> 'media_ambiguous'
    ORDER BY release.display_title, packages.names
""")


def add_disc_variants(connection, catalog, system, markets, *, reviewed=(), reviewed_only=False,
                      status="Prepatched disc image"):
    by_name, by_id = defaultdict(dict), defaultdict(dict)
    by_edition = {}
    for game in catalog["games"]:
        for release in game["releases"]:
            by_edition[release["edition"], release["market"]] = release
            if release["status"] != "matched":
                continue
            scope = frozenset(markets[release["market"]])
            owner = (scope, release)
            archives = release.get("archives", ())
            for name in {*release["titles"], game["title"], *(archive["title"] for archive in archives)}:
                by_name[_title_key(name)][release["key"]] = owner
            for archive in archives:
                by_id[archive["softwareId"]][release["key"]] = owner

    reviews = {item["signature"]: item for item in reviewed}
    result, used = 0, set()
    for record in connection.execute(VARIANTS, dict(zip(("manufacturer", "system"), system))).mappings():
        if record["signature"] in used:
            continue
        review = reviews.get(record["signature"])
        if review:
            release = by_edition.get((review["edition"], review["market"]))
            if release is None or (release["status"] != "matched" and not review.get("allowMissingBase")):
                continue
        else:
            if reviewed_only:
                continue
            regions = set(record["regions"] or ())
            ids = [release for scope, release in by_id[record["software_id"]].values() if scope & regions]
            names = [release for scope, release in by_name[_title_key(record["title"])].values() if scope & regions]
            matches = ids or names
            if len(matches) != 1:
                continue
            release, = matches

        translation = {
            "key": record["signature"], "language": "Undub" if record["modification"] == "undub" else "English",
            "status": status, "version": record["version"], "archiveNames": record["names"],
            "installManifestUrl": f"/api/v1/releases/{record['signature']}/install-manifest",
        }
        if review:
            translation.update(language=review["language"], baseEdition=review["baseEdition"])
        release.setdefault("translations", []).append(translation)
        result += 1
        used.add(record["signature"])
    return result
