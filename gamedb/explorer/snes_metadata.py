"""Present archive metadata and checksum-backed SNES peripheral support."""

from functools import lru_cache
import json

from gamedb.config import PROJECT_ROOT


@lru_cache(maxsize=1)
def peripheral_checksums():
    path = PROJECT_ROOT / "reference/snes_retail_peripherals.json"
    source = json.loads(path.read_text(encoding="utf-8"))
    return {device: set(checksums) for device, checksums in source["devices"].items()}


def add_release_metadata(game, facts):
    if not facts:
        return
    devices = peripheral_checksums()
    for release in game["releases"]:
        values = facts.get(release["key"])
        if not values:
            continue
        metadata = {}
        if values["genres"]:
            metadata["genres"] = values["genres"]
        players = values["players"]
        if len(players) == 1 and players[0].isascii() and players[0].isdecimal():
            if count := int(players[0]):
                metadata["players"] = count
        checksums = set(values["crc32s"])
        peripherals = [device for device, supported in devices.items() if checksums & supported]
        if peripherals:
            metadata["peripherals"] = peripherals
        if metadata:
            release["metadata"] = metadata
