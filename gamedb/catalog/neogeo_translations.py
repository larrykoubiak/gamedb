"""Index reviewed NeoSD patches for the original MVS and AES cartridge sets."""

from collections import defaultdict
from datetime import date
from hashlib import sha256
import json
from zipfile import BadZipFile, ZipFile

from sqlalchemy import text

from gamedb.catalog.neogeo import arcade_sets_sql
from gamedb.catalog.patching import valid_ips
from gamedb.catalog.retail import write_report
from gamedb.catalog.translations import INDEX_NAME, INDEX_VERSION, MAX_PATCH_SIZE, _store_patch, translation_order
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine


REFERENCE = PROJECT_ROOT / "reference/neogeo_translation_reviews.json"


def _read_patch(path, name):
    if path.suffix.lower() == ".zip":
        try:
            with ZipFile(path) as archive, archive.open(name) as member:
                return member.read(MAX_PATCH_SIZE + 1)
        except (BadZipFile, KeyError) as error:
            raise ValueError(f"Missing or unreadable Neo Geo patch {name}") from error
    with path.open("rb") as stream:
        return stream.read(MAX_PATCH_SIZE + 1)


def sync_neogeo_translations(source, root, *, report=None):
    reviews = json.loads(REFERENCE.read_text(encoding="utf-8"))
    sets = reviews["sets"]
    engine = create_database_engine()
    signatures = defaultdict(set)
    try:
        with engine.connect() as connection:
            for row in connection.execute(text(arcade_sets_sql("CAST(:names AS text[])")), {"names": list(sets)}).mappings():
                if row["complete"] and row["installSignature"] in sets[row["setName"]]["signatures"]:
                    signatures[row["setName"]].add(row["installSignature"])
    finally:
        engine.dispose()

    patch_root = root / "patches"
    patch_root.mkdir(parents=True, exist_ok=True)
    records = []
    for project in reviews["projects"]:
        released = (date.fromisoformat(project["released"]) - date(1970, 1, 1)).days * 86400
        for patch in project["patches"]:
            name, set_name = patch["filename"], patch["set"]
            if not signatures[set_name]:
                continue
            data = _read_patch(source / (project.get("archive") or name), name)
            digest = sha256(data).hexdigest()
            if digest != patch["sha256"] or len(data) > MAX_PATCH_SIZE or not valid_ips(data):
                raise ValueError(f"Neo Geo patch checksum or format differs for {name}")
            _store_patch(patch_root / f"{digest}.ips", data)
            records.append({
                "key": sha256(f"{set_name}:neosd:{digest}".encode()).hexdigest(),
                "filename": name, "language": patch["language"], "version": patch.get("version", ""),
                "authors": project["authors"], "releasedAt": released, "status": "Fully Playable",
                "format": "ips", "layout": "neosd", "evidence": "reviewed", "sourceUrl": project["sourceUrl"],
                "size": len(data), "sha256": digest, "signatures": sorted(signatures[set_name]),
                **{field: sets[set_name][field] for field in ("baseMd5", "baseSize") if field in sets[set_name]},
            })
    if not records:
        raise ValueError("No Neo Geo translation patch matched a reviewed arcade set")
    write_report(root / INDEX_NAME, {"version": INDEX_VERSION, "translations": sorted(records, key=translation_order)})
    summary = {"games": sum(bool(items) for items in signatures.values()), "patches": len(records)}
    if report:
        write_report(report, {"summary": summary, "sets": sorted(name for name, items in signatures.items() if items)})
    return summary
