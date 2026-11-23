"""Present archive metadata and peripheral support for retail releases."""

from functools import lru_cache
import json

from gamedb.config import PROJECT_ROOT


@lru_cache(maxsize=1)
def peripheral_checksums():
    path = PROJECT_ROOT / "reference/snes_retail_peripherals.json"
    source = json.loads(path.read_text(encoding="utf-8"))
    return {device: set(checksums) for device, checksums in source["devices"].items()}


def add_release_metadata(game, facts, *, snes_peripherals=True):
    devices = peripheral_checksums() if snes_peripherals and facts else {}
    for release in game["releases"]:
        values = facts.get(release["key"], {})
        metadata = {}
        if values.get("genres"):
            metadata["genres"] = values["genres"]
        players = values.get("players", ())
        if len(players) == 1 and players[0].isascii() and players[0].isdecimal():
            if count := int(players[0]):
                metadata["players"] = count
        checksums = set(values.get("crc32s", ()))
        peripherals = [device for device, supported in devices.items() if checksums & supported]
        if not snes_peripherals:
            peripherals = sorted({device for archive in release.get("archives", ())
                                  for item in archive.get("cartridge", ()) for device in item.get("peripherals", ())})
        if peripherals:
            metadata["peripherals"] = peripherals
        if metadata:
            release["metadata"] = metadata
