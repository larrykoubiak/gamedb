"""Import explicit MAME listxml plus an arcade classification DAT."""

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from sqlalchemy import insert, select, text

from .schema import machine, metadata, source


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_machines(path):
    """Stream machines, retaining XML fields needed for identity and execution."""
    for event, element in ET.iterparse(path, events=("end",)):
        if element.tag not in ("machine", "game"):
            continue
        definition = dict(element.attrib)
        for key in ("description", "year", "manufacturer"):
            definition[key] = element.findtext(key) or ""
        for key in ("rom", "disk", "biosset", "device_ref", "sample", "driver"):
            definition[key] = [dict(child.attrib) for child in element.findall(key)]
        yield definition
        element.clear()


def validate_graph(machines):
    for relationship in ("cloneof", "romof"):
        done = set()
        for name in machines:
            visiting = set()
            current = name
            while current and current not in done:
                if current in visiting:
                    raise ValueError(f"{relationship} cycle at {current}")
                if current not in machines:
                    raise ValueError(f"Unknown {relationship} target {current}")
                visiting.add(current)
                current = machines[current].get(relationship)
            done.update(visiting)
    for name, definition in machines.items():
        for device in definition["device_ref"]:
            if device["name"] not in machines:
                raise ValueError(f"Unknown device {device['name']} in {name}")


def import_mame(engine, xml, arcade_dat, rom_dat_path, chd_dat_path):
    root = next(ET.iterparse(xml, events=("start",)))[1]
    if root.tag != "mame":
        raise ValueError("Expected full MAME -listxml, not a storage DAT")
    build = root.get("build", "")
    version = build.split(" ")[0]
    if not re.fullmatch(r"0\.[0-9]+", version):
        raise ValueError(f"Unsupported MAME build {build!r}")
    arcade_root = ET.parse(arcade_dat).getroot()
    if arcade_root.findtext("header/version") != version:
        raise ValueError("Arcade classification DAT version differs from listxml")
    arcade_names = {e.get("name") for e in arcade_root if e.tag in ("machine", "game")}
    definitions = {d["name"]: d for d in read_machines(xml)}
    # ClrMAMEPro adds synthetic sample containers which are not machines.
    sample_containers = {
        e.get("name")
        for e in arcade_root
        if e.find("sample") is not None
        and e.find("rom") is None
        and e.find("disk") is None
        and not e.get("sourcefile")
    }
    unknown = arcade_names - definitions.keys() - sample_containers
    if not arcade_names or unknown:
        raise ValueError(
            f"Arcade classification contains unknown machines: {sorted(unknown)[:10]}"
        )
    for path in (rom_dat_path, chd_dat_path):
        if version not in Path(path).name:
            raise ValueError("Storage DAT version must match the machine metadata")
    validate_graph(definitions)
    key = f"MAME:{version}"
    snapshot = {
        "source_key": key,
        "version": version,
        "xml_sha256": digest(xml),
        "arcade_sha256": digest(arcade_dat),
        "rom_dat_path": rom_dat_path,
        "chd_dat_path": chd_dat_path,
        "build": build,
    }
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
        metadata.create_all(connection)
        old = (
            connection.execute(select(source).where(source.c.source_key == key))
            .mappings()
            .first()
        )
        if old:
            if dict(old) != snapshot:
                raise ValueError(
                    "This version already has different inputs; use a new explicit source revision"
                )
            return {"source": key, "machines": len(definitions), "unchanged": True}
        if connection.execute(
            select(source.c.source_key).where(source.c.source_key.like("MAME:%"))
        ).first():
            raise ValueError(
                "Only one active MAME version is supported; do not mix storage snapshots"
            )
        for path in (rom_dat_path, chd_dat_path):
            if not connection.execute(
                text(
                    "SELECT 1 FROM staging.rv_files WHERE dat_root_full_name=:path LIMIT 1"
                ),
                {"path": path},
            ).first():
                raise ValueError(f"Storage DAT is absent from rv_files: {path}")
        connection.execute(insert(source), snapshot)
        rows = [
            {
                "source_key": key,
                "name": name,
                "is_arcade": name in arcade_names,
                "definition": d,
            }
            for name, d in definitions.items()
        ]
        for offset in range(0, len(rows), 500):
            connection.execute(insert(machine), rows[offset : offset + 500])
    return {"source": key, "machines": len(rows), "arcade_members": len(arcade_names)}


def import_fbneo(engine, dat, rom_dat_path):
    """Retain an arcade-only FBNeo DAT; CRC declarations are resolved to inventory SHA-1."""
    header = ET.parse(dat).getroot().find("header")
    if header is None or header.findtext("name") != "FinalBurn Neo - Arcade Games":
        raise ValueError("Expected a FinalBurn Neo arcade DAT")
    version = header.findtext("version")
    if not version or version not in Path(rom_dat_path).name:
        raise ValueError("Storage DAT version must match FBNeo metadata")
    definitions = {d["name"]: d for d in read_machines(dat)}
    validate_graph(definitions)
    key = f"FBNeo:{version}"
    snapshot = {
        "source_key": key,
        "version": version,
        "xml_sha256": digest(dat),
        "arcade_sha256": digest(dat),
        "rom_dat_path": rom_dat_path,
        "chd_dat_path": f"unavailable/{key}/disks",
        "build": header.findtext("description"),
    }
    with engine.begin() as connection:
        metadata.create_all(connection)
        old = (
            connection.execute(select(source).where(source.c.source_key == key))
            .mappings()
            .first()
        )
        if old:
            if dict(old) != snapshot:
                raise ValueError("This FBNeo version already has different inputs")
            return {"source": key, "machines": len(definitions), "unchanged": True}
        if connection.execute(
            select(source.c.source_key).where(source.c.source_key.like("FBNeo:%"))
        ).first():
            raise ValueError("Only one active FBNeo snapshot is supported")
        if not connection.execute(
            text(
                "SELECT 1 FROM staging.rv_files WHERE dat_root_full_name=:path LIMIT 1"
            ),
            {"path": rom_dat_path},
        ).first():
            raise ValueError("FBNeo storage DAT is absent from rv_files")
        connection.execute(insert(source), snapshot)
        rows = [
            {"source_key": key, "name": n, "is_arcade": True, "definition": d}
            for n, d in definitions.items()
        ]
        for offset in range(0, len(rows), 500):
            connection.execute(insert(machine), rows[offset : offset + 500])
    return {"source": key, "machines": len(rows)}
