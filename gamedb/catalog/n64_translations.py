"""Resolve Nintendo 64 patch inputs in all three cartridge byte orders."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5, sha1, sha256, sha512
from html import unescape
import json
import re
from zlib import crc32

from gamedb.catalog.cartridges import read_verified_rom
from gamedb.catalog.n64_rom import N64_LAYOUTS, N64_ROM_LIMIT, rom_byte_order
from gamedb.catalog.patching import embedded_input, valid_ips
from gamedb.catalog.retail import write_report
from gamedb.catalog.translations import BaseRoms


CHECKSUM = re.compile(
    r"^[ \t]*\*?[ \t]*(?:(?:file/rom|rom/file|file|rom|original|source|input)[ \t]+)?"
    r"(sha[- ]?1|sha[- ]?512|md[- ]?5|crc(?:[- ]?32)?)"
    r"(?:[ \t]*[:=][ \t]*|[ \t]+|[ \t]*[:=]?[ \t]*\n[ \t]*)(?:0x)?([0-9a-f]{8,128})\b",
    re.I | re.M,
)
OUTPUT_LABEL = re.compile(r"^[ \t]*\*?[ \t]*(?:patched\b|after\b|output\b|once you['’]ve applied)", re.I | re.M)
CHECKSUM_LENGTHS = {"sha1": 40, "sha512": 128, "md5": 32, "crc32": 8}
EXTENSIONS = {"xdelta3": "xdelta", "vcdiff": "xdelta", "xdelta": "xdelta"}


def _fingerprints(rom):
    original = read_verified_rom(rom, max_size=N64_ROM_LIMIT)
    if original is None or len(original) < 64 or len(original) % 4:
        return {}
    fingerprints = {}
    for layout in N64_LAYOUTS:
        try:
            content = rom_byte_order(original, layout)
        except ValueError:
            return {}
        fingerprints[layout] = {
            "size": len(content), "crc32": f"{crc32(content):08x}",
            "sha1": sha1(content).hexdigest(), "md5": md5(content).hexdigest(),
            "sha512": sha512(content).hexdigest(),
        }
    return fingerprints


class Nintendo64Roms(BaseRoms):
    def __init__(self, roms, cache_path):
        super().__init__(roms)
        cached = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
        pending = {digest: rom for digest, rom in self.roms.items() if digest not in cached}
        if pending:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for digest, result in zip(pending, pool.map(_fingerprints, pending.values()), strict=True):
                    if result:
                        cached[digest] = result
            write_report(cache_path, cached)
        self.by_input = defaultdict(set)
        for digest in self.roms:
            for layout, source in cached.get(digest, {}).items():
                for kind in CHECKSUM_LENGTHS:
                    self.by_input[kind, source[kind]].add((digest, layout))
                self.by_input["input", (source["size"], source["crc32"])].add((digest, layout))

    def match_orders(self, claims):
        candidates = [self.by_input[claim] for claim in claims]
        if candidates and len(matches := set.intersection(*candidates)) == 1:
            digest, layout = matches.pop()
            return self.by_sha1[digest], layout
        return None, None


def checksum_claims(rominfo):
    source = unescape(rominfo or "").replace("\r\n", "\n").replace("\r", "\n")
    if output := OUTPUT_LABEL.search(source):
        source = source[:output.start()]
    claims = set()
    for label, digest in CHECKSUM.findall(source):
        kind = label.lower().replace("-", "").replace(" ", "")
        kind = "crc32" if kind == "crc" else kind
        if len(digest) == CHECKSUM_LENGTHS[kind]:
            claims.add((kind, digest.lower()))
    return claims


def match_members(row, path, members, bases, review):
    claims = checksum_claims(row["rominfo"])
    approved = review.get("patches", {}) if review and review["archive"] == path.name else {}
    matches = []
    for name, patch_format, data in members:
        if data is None or patch_format == "ips" and not valid_ips(data):
            continue
        if patch_format in {"bps", "ups"}:
            embedded = embedded_input(data, patch_format)
            base, layout = bases.match_orders([("input", embedded)]) if embedded else (None, None)
            evidence = "embedded"
        elif verified := approved.get(name):
            if sha256(data).hexdigest() != verified["sha256"]:
                continue
            base, layout = bases.by_sha1.get(verified["baseSha1"]), verified["layout"]
            evidence = "reviewed"
        elif len(members) == 1 and row["patchstatus"] != 4:
            base, layout = bases.match_orders(claims)
            evidence = "documented"
        else:
            continue
        if base and layout in N64_LAYOUTS:
            matches.append((name, patch_format, data, base, layout, evidence))
    return matches, None if matches else "no verified patch input"
