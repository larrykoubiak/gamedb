"""Conservative cross-emulator identity and validation of an unchanged bundle."""

from collections import defaultdict

from .resolver import Resolver, chain

CORES = {"MAME": "mame_libretro.so", "FBNeo": "fbneo_libretro.so"}


def game_fingerprint(definitions, name, plan):
    """All game ROMs, excluding BIOS/device contents; never partial overlap."""
    if not plan["complete"] or definitions[name].get("disk"):
        return None
    bios = set()
    for parent in chain(definitions, name)[1:]:
        if definitions[parent].get("isbios") == "yes":
            bios.update(
                (r.get("crc"), int(r["size"]))
                for r in definitions[parent].get("rom", [])
            )
    by_crc = defaultdict(set)
    for asset in plan["assets"]:
        if asset["kind"] != "rom":
            continue
        for member in asset.get("requiredMembers", []):
            if member.get("sha1"):
                by_crc[(member.get("crc"), member["size"])].add(member["sha1"])
    hashes = set()
    for rom in definitions[name].get("rom", []):
        if rom.get("optional") == "yes":
            continue
        identity = (rom.get("crc"), int(rom["size"]))
        if identity in bios:
            continue
        candidates = {rom["sha1"]} if rom.get("sha1") else by_crc[identity]
        if len(candidates) != 1:
            return None
        hashes.add((next(iter(candidates)), int(rom["size"])))
    return frozenset(hashes) if hashes else None


def annotate_sources(sources):
    """Mutate plans with proof-backed family links and package compatibility."""
    mame_families = defaultdict(set)
    for source in sources:
        if source["emulator"] != "MAME":
            continue
        for name, plan in source["plans"].items():
            fingerprint = game_fingerprint(source["definitions"], name, plan)
            if fingerprint:
                mame_families[fingerprint].add((source["key"], plan["family"]))
    for source in sources:
        by_package = defaultdict(list)
        by_disk = {}
        for file in source["files"]:
            if file["kind"] == "rom":
                by_package[file["package_id"]].append(file)
            else:
                by_disk[file["id"]] = file
        links = defaultdict(set)
        if source["emulator"] == "FBNeo":
            for name, plan in source["plans"].items():
                fingerprint = game_fingerprint(source["definitions"], name, plan)
                matches = mame_families.get(fingerprint, set())
                if len(matches) == 1:
                    links[plan["family"]].update(matches)
        for name, plan in source["plans"].items():
            matches = links.get(plan["family"], set())
            family_source, family = (
                next(iter(matches))
                if len(matches) == 1
                else (source["key"], plan["family"])
            )
            plan["identitySource"] = family_source
            plan["identityFamily"] = family
            plan["identityEvidence"] = (
                "exact_game_rom_sha1"
                if matches and len(matches) == 1
                else "source_parent_clone"
            )
            compatible = []
            package_ids = {
                a.get("packageId") for a in plan["assets"] if a["kind"] == "rom"
            }
            disk_ids = {a.get("fileId") for a in plan["assets"] if a["kind"] == "disk"}
            bundled = [f for package_id in package_ids for f in by_package[package_id]]
            bundled.extend(by_disk[file_id] for file_id in disk_ids)
            for target in sources:
                if name not in target["plans"] or not plan["complete"]:
                    continue
                if target is not source:
                    # A different shortname requires a different launch package.
                    resolved = Resolver(
                        target["definitions"], bundled, target["emulator"]
                    ).resolve(name)
                    if (
                        not resolved["complete"]
                        or resolved["launchPath"] != plan["launchPath"]
                    ):
                        continue
                    # Require the actual DAT names (or declared merged names), too.
                    if any(
                        not any(
                            f["kind"] == req["kind"]
                            and f["member"] in (req["name"], req.get("merge"))
                            and f["size"] == int(req.get("size", -1))
                            and (
                                f["sha1"] == req["sha1"]
                                if req.get("sha1")
                                else f["crc"] == req.get("crc")
                            )
                            for f in bundled
                        )
                        for req in resolved["requirements"]
                    ):
                        continue
                compatible.append(
                    {
                        "name": target["emulator"],
                        "core": CORES[target["emulator"]],
                        "version": target["version"],
                        "sourceKey": target["key"],
                        "datSha256": target["digest"],
                        "validation": "dat_validated",
                    }
                )
            compatible.sort(key=lambda item: item["name"] != "FBNeo")
            for entry in compatible:
                if entry["name"] == "FBNeo" and plan.get("samplesDatSha256"):
                    entry["samplesDatSha256"] = plan["samplesDatSha256"]
            plan["compatibleEmulators"] = compatible
            plan["preferredCore"] = (
                compatible[0]["core"] if compatible else CORES[source["emulator"]]
            )
