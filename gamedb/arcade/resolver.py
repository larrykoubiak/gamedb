"""Resolve machine requirements against version-scoped stored inventory."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import PurePosixPath


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Invalid install path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(p in ("", ".", "..") for p in value.split("/"))
        or ":" in value
    ):
        raise ValueError("Invalid install path")
    return value


def chain(machines, name, relationship="romof"):
    result = []
    while name:
        if name in result or name not in machines:
            raise ValueError(f"Invalid {relationship} chain at {name}")
        result.append(name)
        name = machines[name].get(relationship)
    return result


class Resolver:
    def __init__(self, machines, files, emulator="MAME"):
        self.machines = machines
        self.emulator = emulator
        self.inventory = defaultdict(list)
        for file in files:
            self.inventory[(file["kind"], file["set_name"])].append(file)

    def resolve(self, name):
        definition = self.machines[name]
        providers = chain(self.machines, name)
        owners = []
        pending = [name]
        seen = set()
        while pending:
            owner = pending.pop()
            if owner in seen:
                continue
            seen.add(owner)
            owners.append(owner)
            pending.extend(
                d["name"] for d in self.machines[owner].get("device_ref", [])
            )
        assets = {}
        missing = []
        requirements = []
        for owner in owners:
            machine = self.machines[owner]
            search = list(dict.fromkeys(chain(self.machines, owner) + providers))
            # Keep all BIOS choices: packages remain usable with core BIOS overrides.
            for kind in ("rom", "disk"):
                for requirement in machine.get(kind, []):
                    if requirement.get("optional") == "yes":
                        continue
                    expected = dict(requirement, kind=kind, owner=owner)
                    requirements.append(expected)
                    sha1 = requirement.get("sha1")
                    if not sha1 and not (
                        self.emulator == "FBNeo"
                        and requirement.get("crc")
                        and kind == "rom"
                    ):
                        missing.append(
                            dict(
                                expected,
                                reason="undumped"
                                if requirement.get("status") == "nodump"
                                else "missing_hash",
                            )
                        )
                        continue
                    match = None
                    for provider in search:
                        for file in self.inventory[(kind, provider)]:
                            file_hash = (
                                file["disk_sha1"] if kind == "disk" else file["sha1"]
                            )
                            hash_matches = (
                                file_hash == sha1
                                if sha1
                                else file.get("crc")
                                == requirement.get("crc", "").lower()
                            )
                            if hash_matches and (
                                kind == "disk"
                                or file["size"] == int(requirement["size"])
                            ):
                                match = file
                                break
                        if match:
                            break
                    if match is None:
                        missing.append(dict(expected, reason="missing_inventory"))
                        continue
                    if kind == "disk":
                        target = safe_path(f"{name}/{requirement['name']}.chd")
                        asset = {
                            "kind": "disk",
                            "installPath": target,
                            "resolvedPath": match["path"]
                            + "/"
                            + safe_path(match["member"]),
                            "size": match["size"],
                            "sha1": match["sha1"],
                            "diskSha1": sha1,
                            "fileId": match["id"],
                            "requiredMembers": [],
                        }
                    else:
                        target = safe_path(match["archive_name"])
                        asset = {
                            "kind": "rom",
                            "installPath": target,
                            "resolvedPath": match["path"],
                            "packageId": match["package_id"],
                            "requiredMembers": [],
                        }
                    if (
                        target in assets
                        and assets[target]["resolvedPath"] != asset["resolvedPath"]
                    ):
                        raise ValueError(f"Conflicting install target {target}")
                    saved = assets.setdefault(target, asset)
                    if kind == "rom":
                        member = {
                            "name": safe_path(match["member"]),
                            "size": match["size"],
                            "sha1": match["sha1"],
                            "crc": match["crc"],
                        }
                        if member not in saved["requiredMembers"]:
                            saved["requiredMembers"].append(member)
            # Sample files are a separate inventory; absence is explicit, never silently complete.
            for sample in machine.get("sample", []):
                missing.append(
                    {
                        "kind": "sample",
                        "owner": owner,
                        "name": sample["name"],
                        "sampleOf": machine.get("sampleof", owner),
                        "reason": "missing_sample_inventory",
                    }
                )
        # FBNeo's arcade DAT omits the external HDD payload for these families.
        # Do not advertise a ROM-only install as complete.
        if self.emulator == "FBNeo" and chain(self.machines, name, "cloneof")[-1] in (
            "kinst",
            "kinst2",
        ):
            missing.append(
                {"kind": "disk", "name": name, "reason": "missing_hdd_definition"}
            )
        launch = safe_path(name + ".zip")
        if launch not in assets:
            assets[launch] = {
                "kind": "launch",
                "installPath": launch,
                "requiredMembers": [],
            }
        facts = []
        if "neogeo" in providers or "neogeo" in seen:
            facts.append({"key": "hardware", "value": "SNK Neo Geo"})
        for group in re.findall(r"\(([^)]*)\)", definition.get("description", "")):
            region = re.match(r"^(USA|US|Japan|Europe|World)(?:[ ,/]|$)", group)
            if region:
                facts.append(
                    {
                        "key": "region",
                        "value": {
                            "USA": "US",
                            "US": "US",
                            "Japan": "JP",
                            "Europe": "EU",
                            "World": "World",
                        }[region[1]],
                    }
                )
                break
        if "bootleg" in definition.get("manufacturer", "").lower() or re.search(
            r"\b(bootleg|hack)\b", definition.get("description", ""), re.IGNORECASE
        ):
            facts.append({"key": "dump_modification", "value": "hacked"})
        if definition.get("year", "").isdigit():
            facts.append({"key": "release_date", "value": definition["year"]})
        return {
            "facts": facts,
            "sourceDriver": definition.get("sourcefile"),
            "assets": sorted(assets.values(), key=lambda a: a["installPath"]),
            "missing": missing,
            "requirements": requirements,
            "complete": not missing,
            "launchPath": launch,
            "shortname": name,
            "family": chain(self.machines, name, "cloneof")[-1],
            "emulationStatus": (definition.get("driver") or [{}])[0].get(
                "status", "unknown"
            ),
        }


def install_signature(source_key, name, requirements):
    # This identifies a versioned machine definition, not an archive-content identity.
    raw = json.dumps(
        [source_key, name, requirements], sort_keys=True, separators=(",", ":")
    )
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
