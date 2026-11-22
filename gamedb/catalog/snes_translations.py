"""Import translation patches anchored to verified SNES retail ROMs."""

from collections import Counter, defaultdict
from contextlib import closing
from functools import partial
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
from stat import S_ISLNK
from subprocess import DEVNULL, PIPE, Popen, SubprocessError
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZipFile
from zlib import crc32

from libarchive import file_reader
from libarchive.exception import ArchiveError

from gamedb.catalog.snes import write_report
from gamedb.catalog.snes_cartridges import VERIFIED_ROM_SQL
from gamedb.catalog.snes_patching import embedded_input, valid_ips
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.vgm.archives import member_name, safe_member


DEFAULT_ROOT = PROJECT_ROOT / "data/media/snes-translations"
AUTHOR_REFERENCE = PROJECT_ROOT / "reference/snes_translation_authors.json"
INDEX_NAME = ".gamedb-translations.json"
INDEX_VERSION = 1
FORMATS = {"bps", "ips", "ups"}
OTHER_PATCH_FORMATS = {"aps", "ips32", "pat", "ppf", "rup", "vcdiff", "xdelta", "xpatch"}
INPUT_LAYOUTS = {3: "headered", 4: "headerless", 5: "interleaved-headered", 6: "interleaved"}
MAX_PATCH_SIZE = 16 * 1024 * 1024
MAX_PACKAGE_PATCH_BYTES = 64 * 1024 * 1024
TOKEN = re.compile(r"\s*('(?:''|\\.|[^'\\])*'|NULL|-?\d+(?:\.\d+)?|[(),;])", re.S)
ESCAPE = re.compile(r"''|\\(.)", re.S)
MYSQL_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "b": "\b", "Z": "\x1a"}
HASH_CLAIM = re.compile(
    r"^[ \t]*(?:(file/rom|rom/file|file|rom|original|source|input)[ \t]+)?(sha[- ]?1|md5|crc(?:[- ]?32)?)"
    r"(?:[ \t]*[:=][ \t]*|[ \t]+)(?:0x)?([0-9a-f]+)\b", re.I | re.M,
)
OUTPUT_LABEL = re.compile(r"^[ \t]*(?:patched\b|after patching\b|output\b)", re.I | re.M)


def _literal(token):
    if token.startswith("'"):
        return ESCAPE.sub(lambda match: "'" if match[1] is None else MYSQL_ESCAPES.get(match[1], match[1]),
                          token[1:-1])
    if token == "NULL":
        return None
    return float(token) if "." in token else int(token)


def _dump_rows(source, table):
    """Read INSERT literals from a saved RHDN export."""
    data = (source / "scripts" / f"{table}.sql").read_text(encoding="utf-8", errors="replace")
    name = table.replace("-", "_")
    batches = list(re.finditer(rf"^INSERT INTO {name} \(([^)]+)\) VALUES\s*", data, re.M))
    if not batches:
        raise ValueError(f"Missing {table} metadata in the RHDN backup")
    for batch in batches:
        fields = batch[1].split(", ")
        offset = batch.end()
        while True:
            start = TOKEN.match(data, offset)
            if start is None or start[1] != "(":
                raise ValueError(f"Invalid {table} metadata row at offset {offset}")
            offset = start.end()
            row = {}
            for index, field in enumerate(fields):
                value = TOKEN.match(data, offset)
                separator = TOKEN.match(data, value.end()) if value else None
                if (value is None or value[1] in "(),;" or separator is None
                        or separator[1] != ("," if index + 1 < len(fields) else ")")):
                    raise ValueError(f"Invalid {table} metadata field at offset {offset}")
                row[field] = _literal(value[1])
                offset = separator.end()
            yield row
            end = TOKEN.match(data, offset)
            if end is None or end[1] not in (",", ";"):
                raise ValueError(f"Invalid {table} metadata separator at offset {offset}")
            if end[1] == ";":
                break
            offset = end.end()


def _source_archives(source):
    packages = defaultdict(list)
    for path in (source / "translations/snes/patches").iterdir():
        if ((prefix := re.match(r"^\[(\d+)\]", path.name))
                and path.suffix.lower() in (".zip", ".rar", ".7z") and path.is_file()):
            packages[int(prefix[1])].append(path)
    if not packages:
        raise ValueError("No SNES translation packages in the RHDN backup")
    return packages


class BaseRoms:
    """Resolve a consistent set of verified checksums to one ROM identity."""

    def __init__(self, roms):
        self.by_hash = defaultdict(set)
        self.by_sha1 = {}
        for rom in roms:
            base = self.by_sha1.setdefault(rom.sha1, {"sha1": rom.sha1, "signatures": []})
            base["signatures"].append(rom.signature)
            for kind, digest in (("sha1", rom.sha1), ("md5", rom.md5), ("crc32", rom.crc32),
                                 ("input", (rom.size, rom.crc32) if rom.size and rom.crc32 else None)):
                if digest:
                    self.by_hash[kind, digest].add(rom.sha1)

    def match(self, claims):
        candidates = [self.by_hash.get(claim, set()) for claim in claims]
        if candidates and len(matches := set.intersection(*candidates)) == 1:
            return self.by_sha1[matches.pop()]
        return None


def _verified_bases(connection):
    snapshot = connection.exec_driver_sql("SELECT payload FROM app.snes_retail_catalog WHERE singleton").scalar_one_or_none()
    if snapshot is None:
        raise ValueError("Publish the SNES retail catalog before importing translations")
    signatures = sorted({archive["signature"] for game in snapshot["games"] for release in game["releases"]
                         if release["status"] == "matched" for archive in release.get("archives", ())})
    roms = BaseRoms(connection.execute(VERIFIED_ROM_SQL, {"signatures": signatures}))
    if not roms.by_sha1:
        raise ValueError("The published SNES catalog has no verified retail ROMs")
    return roms


def _zip_blocks(path, archive, member):
    if member.compress_type == 9:  # Deflate64 used by some older RHDN ZIPs.
        with Popen(["7z", "x", "-so", "-spd", "--", str(path.resolve()), member.filename],
                   stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL) as process:
            try:
                data = process.stdout.read(member.file_size + 1)
                if len(data) != member.file_size or process.wait(timeout=10) or crc32(data) != member.CRC:
                    raise ValueError("Could not verify Deflate64 archive member")
            finally:
                if process.poll() is None:
                    process.kill()
        yield data
        return
    with archive.open(member) as stream:
        while block := stream.read(64 * 1024):
            yield block


def _archive_members(path):
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            for member in archive.infolist():
                if not member.is_dir() and not S_ISLNK(member.external_attr >> 16):
                    yield member.filename, member.file_size, partial(_zip_blocks, path, archive, member)
        return
    with file_reader(str(path)) as archive:
        for member in archive:
            if member.isfile:
                yield member_name(member), member.size, member.get_blocks


def _patch_members(path):
    members = []
    total_size = 0
    with closing(_archive_members(path)) as archive:
        for member_path, size, blocks in archive:
            name = member_path.replace("\\", "/")
            filename = Path(name).name
            patch_format = Path(filename).suffix.lower().removeprefix(".")
            if patch_format not in FORMATS | OTHER_PATCH_FORMATS:
                continue
            payload = None
            if (patch_format in FORMATS and safe_member(name) and filename.isprintable()
                    and size is not None and 0 < size <= MAX_PATCH_SIZE):
                total_size += size
                if total_size > MAX_PACKAGE_PATCH_BYTES:
                    raise ValueError("Translation package exceeds the patch size limit")
                data = bytearray()
                for block in blocks():
                    if len(data) + len(block) > size:
                        raise ValueError("Incorrect translation patch size")
                    data.extend(block)
                if len(data) != size:
                    raise ValueError("Incomplete translation patch")
                payload = data
            members.append((filename, patch_format, payload))
    return members


def _documented_input(rominfo, layout):
    source = unescape(rominfo or "").replace("\r\n", "\n").replace("\r", "\n")
    if output := OUTPUT_LABEL.search(source):
        source = source[:output.start()]
    hashes = defaultdict(set)
    for scope, label, value in HASH_CLAIM.findall(source):
        kind = label.lower().replace("-", "").replace(" ", "")
        if kind == "crc":
            kind = "crc32"
        if len(value) == {"sha1": 40, "md5": 32, "crc32": 8}[kind]:
            hashes[scope.lower()].add((kind, value.lower()))
    if layout != "headerless" and hashes["rom"]:
        # RHDN sometimes records both the original ROM and the prepared file.
        return hashes["rom"] | hashes["file/rom"] | hashes["rom/file"]
    return set().union(*hashes.values())


def _package_matches(row, path, bases):
    try:
        members = _patch_members(path)
    except (ArchiveError, BadZipFile, NotImplementedError, OSError, RuntimeError, SubprocessError, ValueError):
        return [], "unreadable package"
    matches = []
    for name, patch_format, data in members:
        if data is None:
            continue
        if patch_format == "ips":
            # A package-level checksum cannot assign separate IPS files to inputs.
            layout = INPUT_LAYOUTS.get(row["patchhint"])
            if len(members) != 1 or not layout or row["patchstatus"] == 4 or not valid_ips(data):
                continue
            base = bases.match(_documented_input(row["rominfo"], layout))
            evidence = "documented"
        else:
            layout = "headerless"
            embedded = embedded_input(data, patch_format)
            base = bases.match([("input", embedded)]) if embedded else None
            evidence = "embedded"
        if base:
            matches.append((name, patch_format, data, base, layout, evidence))
    return matches, None if matches else "no verified patch input"


def _store_patch(path, data):
    if path.is_file() and path.stat().st_size == len(data) and path.read_bytes() == data:
        return
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            temporary.chmod(0o644)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def translation_order(record):
    language = record["language"].casefold()
    return language != "english", language, -record["releasedAt"], record["filename"].casefold(), record["key"]


def _translation_authors(source, rows):
    reference = json.loads(AUTHOR_REFERENCE.read_text(encoding="utf-8"))
    names = reference["authors"]
    credited = defaultdict(list)
    if (source / "scripts/transauthor-project.sql").is_file():
        for row in _dump_rows(source, "transauthor-project"):
            if name := names.get(str(row["person"])):
                credited[row["project"]].append(name)
    authors = {}
    for row in rows:
        project = row["transkey"]
        saved = reference["projectCredits"].get(str(project))
        if (saved and saved["version"] == unescape(row["patchver"] or "").strip()
                and saved["releasedAt"] == row["patchrel_unix"]):
            authors[project] = saved["authors"]
        elif credited[project]:
            authors[project] = list(dict.fromkeys(credited[project]))
        elif name := names.get(str(row.get("groupkey"))):
            authors[project] = [name]
    return authors


def _import_translations(source, root, bases):
    consoles = {row["consolekey"]: row["consoleid"] for row in _dump_rows(source, "console")}
    languages = {row["id"]: unescape(row["name"]) for row in _dump_rows(source, "language")}
    statuses = {row["id"]: row["description"] for row in _dump_rows(source, "patchstatus")}
    rows = [row for row in _dump_rows(source, "transdata") if row["consolekey"] == consoles["snes"]]
    authors = _translation_authors(source, rows)
    archives = _source_archives(source)
    skipped = Counter()
    packages = []
    for row in rows:
        paths = archives.get(row["transkey"], ())
        filename = unescape(row["patchfile"] or "").casefold()
        paths = [path for path in paths if path.name.casefold() == filename] or paths
        if len(paths) != 1:
            skipped["missing or ambiguous archive"] += 1
        else:
            packages.append((row, paths[0]))
    if not packages:
        raise ValueError("Could not locate any archives for the SNES translation records")

    patch_root = root / "patches"
    patch_root.mkdir(parents=True, exist_ok=True)
    translations = {}
    for row, path in packages:
        matches, reason = _package_matches(row, path, bases)
        if reason:
            skipped[reason] += 1
        language = languages[row["language"]]
        for name, patch_format, data, base, layout, evidence in matches:
            digest = sha256(data).hexdigest()
            key = sha256(f"{base['sha1']}:{language.casefold()}:{layout}:{digest}".encode()).hexdigest()
            record = {
                "key": key, "rhdnId": row["transkey"], "language": language,
                "authors": authors.get(row["transkey"], []),
                "version": unescape(row["patchver"] or "").strip(),
                "status": statuses[row["patchstatus"]], "releasedAt": row["patchrel_unix"] or 0,
                "filename": name, "format": patch_format, "layout": layout, "evidence": evidence,
                "size": len(data), "sha256": digest, "baseSha1": base["sha1"], "signatures": base["signatures"],
            }
            _store_patch(patch_root / f"{digest}.{patch_format}", data)
            if key not in translations or record["releasedAt"] > translations[key]["releasedAt"]:
                translations[key] = record
    records = sorted(translations.values(), key=translation_order)
    if not records:
        raise ValueError("No translation patches matched the verified SNES catalog")
    write_report(root / INDEX_NAME, {"version": INDEX_VERSION, "translations": records})
    return {
        "sourceRecords": len(rows),
        "patches": len(records),
        "withAuthors": sum(bool(record["authors"]) for record in records),
        "baseRoms": len({record["baseSha1"] for record in records}),
        "languages": dict(Counter(record["language"] for record in records)),
        "formats": dict(Counter(record["format"] for record in records)),
        "skippedPackages": dict(skipped),
    }


def sync_translations(source, root):
    database = create_database_engine()
    try:
        with database.begin() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            bases = _verified_bases(connection)
    finally:
        database.dispose()
    return _import_translations(source, root, bases)
