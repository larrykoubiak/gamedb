"""Import translation patches anchored to verified retail ROMs."""

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

from gamedb.catalog.retail import RETAIL_PLATFORMS, retail_tables, write_report
from gamedb.catalog.cartridges import VERIFIED_ROM_SQL
from gamedb.catalog.patching import embedded_input, supports_patching, valid_ips
from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.vgm.archives import member_name, safe_member


TRANSLATION_ROOTS = {platform: PROJECT_ROOT / f"data/media/{platform}-translations" for platform in RETAIL_PLATFORMS}
RHDN_CONSOLES = {"snes": "snes", "megadrive": "genesis"}
AUTHOR_REFERENCE = PROJECT_ROOT / "reference/snes_translation_authors.json"
MEGADRIVE_REVIEWS = PROJECT_ROOT / "reference/megadrive_translation_reviews.json"
INDEX_NAME = ".gamedb-translations.json"
INDEX_VERSION = 1
FORMATS = {"bps", "ips", "ups"}
OTHER_PATCH_FORMATS = {"aps", "ips32", "pat", "ppf", "rup", "vcdiff", "xdelta", "xpatch"}
SNES_LAYOUTS = {3: "headered", 4: "headerless", 5: "interleaved-headered", 6: "interleaved"}
MEGADRIVE_LAYOUTS = {8: "headerless", 9: "interleaved-headered"}
MAX_PATCH_SIZE = 16 * 1024 * 1024
MAX_PACKAGE_PATCH_BYTES = 64 * 1024 * 1024
TOKEN = re.compile(r"\s*('(?:''|\\.|[^'\\])*'|NULL|-?\d+(?:\.\d+)?|[(),;])", re.S)
ESCAPE = re.compile(r"''|\\(.)", re.S)
MYSQL_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "b": "\b", "Z": "\x1a"}
HASH_CLAIM = re.compile(
    r"^[ \t]*(?:(file/rom|rom/file|file|rom|original|source|input)[ \t]+)?(sha[- ]?1|md5|crc(?:[- ]?32)?)"
    r"(?:[ \t]*[:=][ \t]*|[ \t]+)(?:0x)?([0-9a-f]+(?:[ \t]+[0-9a-f]{4,16}\b)*)\b", re.I | re.M,
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


def _source_archives(source, platform):
    packages = defaultdict(list)
    for path in (source / "translations" / RHDN_CONSOLES[platform] / "patches").iterdir():
        if ((prefix := re.match(r"^\[(\d+)\]", path.name))
                and (path.suffix.lower() in {".zip", ".rar", ".7z"} or path.name.lower().endswith(".tar.gz"))
                and path.is_file()):
            packages[int(prefix[1])].append(path)
    if not packages:
        raise ValueError(f"No {RETAIL_PLATFORMS[platform]} translation packages in the RHDN backup")
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


def _verified_bases(connection, platform):
    table, _, _ = retail_tables(platform)
    label = RETAIL_PLATFORMS[platform]
    if not connection.exec_driver_sql(f"SELECT to_regclass('{table}') IS NOT NULL").scalar_one():
        raise ValueError(f"Publish the {label} retail catalog before importing translations")
    snapshot = connection.exec_driver_sql(f"SELECT payload FROM {table} WHERE singleton").scalar_one_or_none()
    if snapshot is None:
        raise ValueError(f"Publish the {label} retail catalog before importing translations")
    signatures = sorted({archive["signature"] for game in snapshot["games"] for release in game["releases"]
                         if release["status"] == "matched" for archive in release.get("archives", ())})
    roms = BaseRoms(connection.execute(VERIFIED_ROM_SQL, {"signatures": signatures}))
    if not roms.by_sha1:
        raise ValueError(f"The published {label} catalog has no verified retail ROMs")
    return roms


def _sevenzip_member(path, name, size, expected_crc=None):
    with Popen(["7z", "x", "-so", "-spd", "--", str(path.resolve()), name],
               stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL) as process:
        try:
            data = process.stdout.read(size + 1)
            if len(data) != size or process.wait(timeout=10):
                raise ValueError("Could not verify translation archive member")
            if expected_crc is not None and crc32(data) != expected_crc:
                raise ValueError("Translation archive member checksum changed")
            return data
        finally:
            if process.poll() is None:
                process.kill()


def _zip_blocks(path, archive, member):
    if member.compress_type == 9:  # Deflate64 used by some older RHDN ZIPs.
        yield _sevenzip_member(path, member.filename, member.file_size, member.CRC)
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
                try:
                    for block in blocks():
                        if len(data) + len(block) > size:
                            raise ValueError("Incorrect translation patch size")
                        data.extend(block)
                except ArchiveError:
                    if path.suffix.lower() != ".rar":
                        raise
                    data = _sevenzip_member(path, member_path, size)
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
        value = "".join(value.split())
        if len(value) == {"sha1": 40, "md5": 32, "crc32": 8}[kind]:
            hashes[scope.lower()].add((kind, value.lower()))
    if layout != "headerless" and hashes["rom"]:
        # RHDN sometimes records both the original ROM and the prepared file.
        return hashes["rom"] | hashes["file/rom"] | hashes["rom/file"]
    return set().union(*hashes.values())


def _package_matches(row, path, bases, *, layouts=SNES_LAYOUTS, review=None):
    try:
        members = _patch_members(path)
    except (ArchiveError, BadZipFile, NotImplementedError, OSError, RuntimeError, SubprocessError, ValueError):
        return [], "unreadable package"
    if not any(data is not None for _, _, data in members):
        return [], "no supported patch file"
    matches = []
    for name, patch_format, data in members:
        if data is None:
            continue
        if patch_format == "ips":
            layout = layouts.get(row["patchhint"])
            if not layout or row["patchstatus"] == 4 or not valid_ips(data):
                continue
            if review and review["archive"] == path.name:
                if review["patches"].get(name) != sha256(data).hexdigest():
                    continue
                base = bases.by_sha1.get(review["baseSha1"])
                layout = review.get("layout", layout)
                evidence = "reviewed"
            elif len(members) == 1:
                base = bases.match(_documented_input(row["rominfo"], layout))
                evidence = "documented"
            else:
                continue
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


def _translation_authors(source, rows, additional=None):
    reference = json.loads(AUTHOR_REFERENCE.read_text(encoding="utf-8"))
    names = reference["authors"] | (additional or {})
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


def _import_translations(source, root, bases, *, platform="snes", report=None):
    label = RETAIL_PLATFORMS[platform]
    reviews = json.loads(MEGADRIVE_REVIEWS.read_text(encoding="utf-8")) if platform == "megadrive" else {}
    layouts = MEGADRIVE_LAYOUTS if platform == "megadrive" else SNES_LAYOUTS
    consoles = {row["consolekey"]: row["consoleid"] for row in _dump_rows(source, "console")}
    languages = {row["id"]: unescape(row["name"]) for row in _dump_rows(source, "language")}
    statuses = {row["id"]: row["description"] for row in _dump_rows(source, "patchstatus")}
    console = consoles[RHDN_CONSOLES[platform]]
    rows = [row for row in _dump_rows(source, "transdata") if row["consolekey"] == console]
    authors = _translation_authors(source, rows, reviews.get("authors"))
    archives = _source_archives(source, platform)
    titles = ({r["gamekey"]: unescape(r["gametitle"] or "") for r in _dump_rows(source, "gamedata")
               if r["platformid"] == console} if report and (source / "scripts/gamedata.sql").is_file() else {})
    skipped = Counter()
    unresolved = []

    def skip(row, reason):
        skipped[reason] += 1
        if report:
            unresolved.append({"rhdnId": row["transkey"], "title": titles.get(row.get("gamekey")),
                               "language": languages[row["language"]], "reason": reason})

    packages = []
    for row in rows:
        paths = archives.get(row["transkey"], ())
        filename = unescape(row["patchfile"] or "").casefold()
        paths = [path for path in paths if path.name.casefold() == filename] or paths
        if len(paths) != 1:
            skip(row, "missing or ambiguous archive")
        else:
            packages.append((row, paths[0]))
    if not packages:
        raise ValueError(f"Could not locate any archives for the {label} translation records")

    patch_root = root / "patches"
    patch_root.mkdir(parents=True, exist_ok=True)
    translations = {}
    for row, path in packages:
        review = reviews.get("ips", {}).get(str(row["transkey"]))
        matches, reason = _package_matches(row, path, bases, layouts=layouts, review=review)
        if reason:
            skip(row, reason)
        language = languages[row["language"]]
        version = unescape(row["patchver"] or "").strip()
        for name, patch_format, data, base, layout, evidence in matches:
            digest = sha256(data).hexdigest()
            fingerprint = f"{base['sha1']}:{language.casefold()}:{layout}:{digest}"
            member_review = review if evidence == "reviewed" else {}
            pad_to_size = member_review.get("padToSize")
            if pad_to_size is not None:
                fingerprint += f":{pad_to_size}"
            key = sha256(fingerprint.encode()).hexdigest()
            record = {
                "key": key, "rhdnId": row["transkey"], "language": language,
                "authors": authors.get(row["transkey"], []),
                "version": member_review.get("versions", {}).get(name, version),
                "status": statuses[row["patchstatus"]], "releasedAt": row["patchrel_unix"] or 0,
                "filename": name, "format": patch_format, "layout": layout, "evidence": evidence,
                "size": len(data), "sha256": digest, "baseSha1": base["sha1"], "signatures": base["signatures"],
            }
            if pad_to_size is not None:
                record["padToSize"] = pad_to_size
            _store_patch(patch_root / f"{digest}.{patch_format}", data)
            if key not in translations or record["releasedAt"] > translations[key]["releasedAt"]:
                translations[key] = record
    records = sorted(translations.values(), key=translation_order)
    if not records:
        raise ValueError(f"No translation patches matched the verified {label} catalog")
    write_report(root / INDEX_NAME, {"version": INDEX_VERSION, "translations": records})
    summary = {
        "sourceRecords": len(rows),
        "matchedProjects": len(rows) - sum(skipped.values()),
        "patches": len(records),
        "romDownloads": sum(supports_patching(record["format"], record["layout"]) for record in records),
        "withAuthors": sum(bool(record["authors"]) for record in records),
        "baseRoms": len({record["baseSha1"] for record in records}),
        "languages": dict(Counter(record["language"] for record in records)),
        "formats": dict(Counter(record["format"] for record in records)),
        "skippedPackages": dict(skipped),
    }
    if report:
        write_report(report, {"summary": summary, "unresolved": unresolved})
    return summary


def sync_translations(source, root, *, platform="snes", report=None):
    if source.name == RHDN_CONSOLES[platform] and source.parent.name == "translations":
        source = source.parent.parent
    database = create_database_engine()
    try:
        with database.begin() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            bases = _verified_bases(connection, platform)
    finally:
        database.dispose()
    return _import_translations(source, root, bases, platform=platform, report=report)
