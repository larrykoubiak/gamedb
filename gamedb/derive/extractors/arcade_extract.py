"""Interpret MAME machine families and resolve version-matched install plans."""

from sqlalchemy import insert, select, text

from gamedb.arcade.compatibility import annotate_sources
from gamedb.arcade.resolver import Resolver, install_signature
from gamedb.arcade.samples import attach_samples, load_samples
from gamedb.arcade.schema import machine, source
from gamedb.arcade.schema import metadata as staging_metadata

from ..schema import arcade_release, record, source_release, source_release_package


class ArcadeExtractor:
    def execute(self, connection):
        staging_metadata.create_all(connection)
        arcade_release.create(connection, checkfirst=True)
        # The record FK needs its own index for selective arcade refreshes.
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS derived_release_package_record_idx "
                "ON derived.source_release_package (archive_name_id, record_index)"
            )
        )
        connection.execute(text("DROP SCHEMA IF EXISTS catalog CASCADE"))
        connection.execute(
            text(
                "DELETE FROM derived.source_release WHERE dat_id IN (SELECT id FROM derived.dat WHERE romset IN ('MAME','FBNeo'))"
            )
        )
        connection.execute(
            text(
                "DELETE FROM derived.record WHERE archive_name_id IN (SELECT id FROM derived.archive_name WHERE romset IN ('MAME','FBNeo'))"
            )
        )
        count = 0
        contexts = []
        interpretations = []
        for src in connection.execute(select(source)).mappings():
            dat = (
                connection.execute(
                    text(
                        "SELECT id, canonical_system_id FROM derived.dat WHERE dat_path=:path"
                    ),
                    {"path": src["rom_dat_path"]},
                )
                .mappings()
                .first()
            )
            if dat is None:
                raise ValueError("Run derivation from dat before arcade interpretation")
            rows = list(
                connection.execute(
                    select(machine).where(machine.c.source_key == src["source_key"])
                ).mappings()
            )
            definitions = {r["name"]: r["definition"] for r in rows}
            files = list(
                connection.execute(
                    text("""
                SELECT f.id, f.package_id, f.member_path AS member, f.size,
                    lower(f.sha1_hex) AS sha1, lower(f.alt_sha1_hex) AS disk_sha1,
                    lower(f.crc_hex) AS crc, a.archive_name, a.id AS archive_name_id,
                    pth.resolved_path AS path,
                    CASE WHEN d.dat_path=:rom THEN 'rom' ELSE 'disk' END AS kind,
                    CASE WHEN right(a.archive_name,4)='.zip' THEN left(a.archive_name,-4) ELSE a.archive_name END AS set_name
                FROM derived.file f JOIN derived.package p ON p.id=f.package_id
                JOIN derived.archive_name a ON a.id=p.archive_name_id
                JOIN derived.dat d ON d.id=p.dat_id
                JOIN derived.package_path pth ON pth.package_id=p.id
                WHERE d.dat_path IN (:rom,:chd)
                ORDER BY f.id
            """),
                    {"rom": src["rom_dat_path"], "chd": src["chd_dat_path"]},
                ).mappings()
            )
            if any(f["path"] is None for f in files):
                raise ValueError(
                    "Resolve MAME package paths before arcade interpretation"
                )
            emulator = src["source_key"].split(":")[0]
            resolver = Resolver(definitions, files, emulator)
            sample_definitions, sample_inventory, sample_digest = load_samples(
                connection, src["source_key"]
            )
            plans = {}
            contexts.append(
                {
                    "key": src["source_key"],
                    "emulator": emulator,
                    "version": src["version"],
                    "digest": src["xml_sha256"],
                    "definitions": definitions,
                    "files": files,
                    "plans": plans,
                }
            )
            packages = {f["set_name"]: f for f in files if f["kind"] == "rom"}
            available_names = {f["set_name"] for f in files}
            release_rows, interpretation_rows, record_rows, memberships = [], [], [], []
            for row in sorted(rows, key=lambda r: r["name"]):
                d = row["definition"]
                name = row["name"]
                if (
                    not row["is_arcade"]
                    or d.get("isbios") == "yes"
                    or d.get("isdevice") == "yes"
                    or d.get("runnable") == "no"
                ):
                    continue
                plan = attach_samples(
                    resolver.resolve(name),
                    sample_definitions,
                    sample_inventory,
                    sample_digest,
                )
                # Include inherited/disk-only variants, but not absent machines with no resolved content.
                if name not in available_names and not any(
                    a["kind"] != "launch" for a in plan["assets"]
                ):
                    continue
                plans[name] = plan
                ordinal = len(release_rows) + 1
                family_title = definitions[plan["family"]]["description"]
                release_rows.append(
                    {
                        "dat_id": dat["id"],
                        "group_ordinal": ordinal,
                        "canonical_system_id": dat["canonical_system_id"],
                        "title_text": family_title,
                        "grouping_status": "standalone",
                        "expected_media_parts": None,
                        "available_media_parts": None,
                        "needs_review": not plan["complete"],
                    }
                )
                interpretation_rows.append(
                    {
                        "dat_id": dat["id"],
                        "group_ordinal": ordinal,
                        "source_key": src["source_key"],
                        "shortname": name,
                        "family": plan["family"],
                        "description": d["description"],
                        "version": src["version"],
                        "install_signature": install_signature(
                            src["source_key"], name, plan["requirements"]
                        ),
                        "plan": plan,
                    }
                )
                if name in packages:
                    package = packages[name]
                    record_rows.append(
                        {
                            "archive_name_id": package["archive_name_id"],
                            "record_index": 1,
                            "title_text": d["description"],
                            "source_start": 0,
                            "source_end": len(package["archive_name"]),
                            "parse_status": "parsed",
                            "parse_issues": [],
                            "classification_issues": [],
                            "grouping_signature": name,
                        }
                    )
                    memberships.append(
                        {
                            "source_dat_id": dat["id"],
                            "source_group_ordinal": ordinal,
                            "package_id": package["package_id"],
                            "archive_name_id": package["archive_name_id"],
                            "record_index": 1,
                        }
                    )
            for table, values in (
                (record, record_rows),
                (source_release, release_rows),
                (source_release_package, memberships),
            ):
                for offset in range(0, len(values), 250):
                    connection.execute(insert(table), values[offset : offset + 250])
            interpretations.extend(interpretation_rows)
            count += len(release_rows)
        annotate_sources(contexts)
        for offset in range(0, len(interpretations), 250):
            connection.execute(
                insert(arcade_release), interpretations[offset : offset + 250]
            )
        return count
