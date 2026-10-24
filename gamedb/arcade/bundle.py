"""Validate physical dependencies and stream a ZIP64 MAME installation bundle."""

import json
import shutil
import zipfile
from pathlib import Path

from .resolver import safe_path


def resolve_path(root, value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing source path")
    path = Path(value).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def prepare_manifest(manifest, root):
    """Return a public plan plus private locators; never expose host paths."""
    plan = manifest["plan"]
    result = {k: v for k, v in manifest.items() if k != "plan"}
    result.update(
        shortname=plan["shortname"],
        family=plan["family"],
        launchPath="roms/" + safe_path(plan["launchPath"]),
        emulationStatus=plan["emulationStatus"],
        missing=list(plan["missing"]),
        packages=[],
        installRoot="roms",
        systemDirectory=plan.get("systemDirectory"),
        preferredCore=plan.get("preferredCore", "mame_libretro.so"),
        compatibleEmulators=plan.get("compatibleEmulators", []),
    )
    for source in plan["assets"]:
        install_root = source.get("installRoot", "roms")
        if install_root not in ("roms", "system"):
            raise ValueError("Invalid asset install root")
        target = install_root + "/" + safe_path(source["installPath"])
        asset = {
            k: v
            for k, v in source.items()
            if k not in ("resolvedPath", "fileId", "packageId")
        }
        asset["installPath"] = target
        try:
            if source["kind"] != "launch":
                path = resolve_path(root, source.get("resolvedPath"))
                asset["size"] = path.stat().st_size
                if source["kind"] == "disk" and asset["size"] != source["size"]:
                    raise ValueError("Disk size changed")
                if source["kind"] in ("rom", "sample"):
                    with zipfile.ZipFile(path) as archive:
                        for expected in source["requiredMembers"]:
                            member = archive.getinfo(expected["name"])
                            if member.file_size != expected["size"] or (
                                expected["crc"]
                                and member.CRC != int(expected["crc"], 16)
                            ):
                                raise ValueError("ROM archive changed")
                asset["_path"] = path
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            result["missing"].append(
                {
                    "kind": source["kind"],
                    "name": target,
                    "reason": "missing_or_changed_file",
                }
            )
        result["packages"].append(asset)
    result["complete"] = not result["missing"]
    if not result["complete"]:
        result["compatibleEmulators"] = []
    result["bundleUrl"] = (
        f"/api/v1/releases/{manifest['releaseSignature']}/install-bundle"
        if result["complete"]
        else None
    )
    return result


def public_manifest(manifest):
    result = dict(manifest)
    result["packages"] = [
        {k: v for k, v in a.items() if not k.startswith("_")}
        for a in manifest["packages"]
    ]
    return result


class StreamingOutput:
    """Unseekable output makes zipfile emit data descriptors without buffering."""

    def __init__(self, stream):
        self.stream = stream
        self.position = 0

    def write(self, data):
        self.stream.write(data)
        self.position += len(data)
        return len(data)

    def tell(self):
        return self.position

    def flush(self):
        self.stream.flush()


def write_bundle(stream, manifest):
    if not manifest["complete"]:
        raise ValueError("Cannot package an incomplete machine")
    with zipfile.ZipFile(
        StreamingOutput(stream), "w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as bundle:
        bundle.writestr(
            "gamedb-install.json", json.dumps(public_manifest(manifest), indent=2)
        )
        for asset in manifest["packages"]:
            target = safe_path(asset["installPath"])
            if asset["kind"] == "launch":
                # A disk-only or fully inherited variant still needs a launch filename.
                import io

                empty = io.BytesIO()
                with zipfile.ZipFile(empty, "w"):
                    pass
                bundle.writestr(target, empty.getvalue())
            else:
                info = zipfile.ZipInfo(target)
                info.file_size = asset["size"]
                with (
                    asset["_path"].open("rb") as source,
                    bundle.open(info, "w", force_zip64=True) as destination,
                ):
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
