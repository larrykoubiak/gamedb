"""Build reviewed translation sets from published Redump releases."""

from collections import Counter, defaultdict
from contextlib import closing
from hashlib import file_digest, sha1, sha256
from html import unescape
import json
from pathlib import Path
import re
from shutil import copyfile, copyfileobj, which
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from libarchive.exception import ArchiveError
from sqlalchemy import text

from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine
from gamedb.exo.media import location_path
from gamedb.vgm.archives import safe_member

from .disc_patching import DISC_PATCH_EXTENSIONS, patch_disc_image, repair_xa_form1_checksums
from .retail import retail_tables, write_report
from .translations import (
    DISC_LAYOUT, DISC_PATCH_ARCHIVES, INDEX_NAME, INDEX_VERSION, RHDN_CONSOLES, _archive_members, _dump_rows,
    _sevenzip_member, _translation_authors, translation_order,
)


FILE_LINE = re.compile(r'^\s*FILE +"([^"\r\n]+)" +BINARY\s*$', re.I | re.M)
CHUNK_SIZE = 1024 * 1024

BASE_FILES = text("""
    SELECT DISTINCT signature.sha1_set_digest AS signature, package.archive_name AS archive,
           package.resolved_path AS path, file.member_path AS name, file.sha1_hex AS sha1,
           file.size, file.sha1_verified AS verified
    FROM catalog.release_content_signature signature
    JOIN catalog.release_package part ON part.release_id = signature.release_id
    JOIN catalog.package package ON package.id = part.package_id
    JOIN catalog.package_file file ON file.package_id = package.id
    WHERE signature.sha1_set_digest = ANY(CAST(:signatures AS text[]))
      AND package.source_collection = 'Redump' AND package.resolved_path IS NOT NULL
    ORDER BY signature, archive, name
""")


def _digest(path, algorithm):
    with path.open("rb") as stream:
        return file_digest(stream, algorithm).hexdigest()


def _reviewed_bases(connection, platform, reviews):
    table, _, _ = retail_tables(platform)
    if connection.exec_driver_sql(f"SELECT to_regclass('{table}')").scalar_one() is None:
        raise ValueError(f"Publish the {platform} retail catalog before importing translations")
    catalog = connection.exec_driver_sql(f"SELECT payload FROM {table} WHERE singleton").scalar_one_or_none()
    if catalog is None:
        raise ValueError(f"Publish the {platform} retail catalog before importing translations")
    wanted = {tuple(disc["archiveName"] for disc in review["discs"]) for review in reviews.values()}
    published = defaultdict(dict)
    for game in catalog["games"]:
        for release in game["releases"]:
            if release["status"] != "matched":
                continue
            for archive in release["archives"]:
                names = tuple(archive["archiveNames"])
                if names in wanted and archive["regions"] == ["US"]:
                    published[names].setdefault(archive["signature"], game["title"])
    signatures = sorted({signature for matches in published.values() for signature in matches})
    files = defaultdict(list)
    for row in connection.execute(BASE_FILES, {"signatures": signatures}).mappings():
        files[row["signature"], row["archive"]].append(dict(row))
    return published, files


def _extract_patches(archive, plan, work):
    wanted = {step for disc in plan for step in disc["patches"]}
    extracted = {}
    with closing(_archive_members(archive)) as members:
        for name, size, blocks in members:
            if name not in wanted:
                continue
            extension = Path(name).suffix.lower()
            if name in extracted or not safe_member(name) or extension not in DISC_PATCH_EXTENSIONS or not size:
                raise ValueError(f"Invalid disc patch member: {name}")
            path = work / f"patch-{len(extracted)}{extension}"
            try:
                with path.open("wb") as output:
                    for block in blocks():
                        if output.tell() + len(block) > size:
                            raise ValueError(f"Disc patch member exceeds its recorded size: {name}")
                        output.write(block)
            except ArchiveError:
                if archive.suffix.lower() != ".rar":
                    raise
                path.write_bytes(_sevenzip_member(archive, name, size))
            if path.stat().st_size != size:
                raise ValueError(f"Incomplete disc patch member: {name}")
            extracted[name] = path
    if extracted.keys() != wanted:
        raise ValueError("A reviewed disc patch member is missing")
    return extracted


def _write_verified(source, output, member):
    size, checksum = 0, sha1()
    with source.open(member["name"]) as stream:
        while block := stream.read(CHUNK_SIZE):
            size += len(block)
            if size > member["size"]:
                raise ValueError(f"Disc member grew: {member['name']}")
            checksum.update(block)
            output.write(block)
    if size != member["size"] or checksum.hexdigest() != member["sha1"]:
        raise ValueError(f"Disc member checksum changed: {member['name']}")


def _build_disc(bundle, members, disc, patches, work, rom_root):
    paths = {member["path"] for member in members}
    if len(paths) != 1 or not all(member["verified"] and member["size"] for member in members):
        raise ValueError(f"The verified disc is unavailable: {disc['archiveName']}")
    names = {member["name"] for member in members}
    if len(names) != len(members) or any(Path(name).name != name or "\\" in name or not safe_member(name)
                                        or not name.isprintable() or name in bundle.namelist() for name in names):
        raise ValueError(f"Conflicting disc member names: {disc['archiveName']}")
    cue, = [member for member in members if Path(member["name"]).suffix.lower() == ".cue"]
    data, = [member for member in members if Path(member["name"]).suffix.lower() == ".bin"
             and member["sha1"] == disc["inputSha1"]]
    source_path = location_path(rom_root, paths.pop())
    with ZipFile(source_path) as source, TemporaryDirectory(dir=work) as directory:
        input_names = [member.filename for member in source.infolist() if not member.is_dir()]
        if set(input_names) != names or len(input_names) != len(names):
            raise ValueError(f"Disc archive contents changed: {disc['archiveName']}")
        if source.getinfo(cue["name"]).file_size != cue["size"]:
            raise ValueError(f"Disc member size changed: {cue['name']}")
        if set(FILE_LINE.findall(source.read(cue["name"]).decode("cp1252"))) != {
            name for name in names if Path(name).suffix.lower() == ".bin"
        }:
            raise ValueError(f"The cue sheet does not describe the archived tracks: {cue['name']}")
        temporary = Path(directory)
        source_image = temporary / "source.bin"
        repair_checksums = disc.get("repairXaChecksums", False)
        original = source_image
        with original.open("wb") as output:
            _write_verified(source, output, data)
        for index, step in enumerate(disc["patches"]):
            target = temporary / f"target-{index}.bin"
            patch_disc_image(original, patches[step], target)
            if index or not repair_checksums:
                original.unlink()
            original = target
        if repair_checksums:
            repair_xa_form1_checksums(source_image, original)
        if _digest(original, "sha1") != disc["outputSha1"]:
            raise ValueError(f"Patched disc checksum differs from the reviewed build: {disc['archiveName']}")
        for member in members:
            with bundle.open(member["name"], "w", force_zip64=True) as output:
                if member == data:
                    with original.open("rb") as stream:
                        copyfileobj(stream, output, CHUNK_SIZE)
                else:
                    _write_verified(source, output, member)
    return cue["name"]


def _store_artifact(directory, temporary, digest):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{digest}{temporary.suffix.lower()}"
    temporary.chmod(0o644)
    try:
        target.hardlink_to(temporary)
    except FileExistsError:
        if _digest(target, "sha256") != digest:
            temporary.replace(target)
    stat = target.stat()
    return {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns, "sha256": digest}


def _project_archive(source, root, platform, review):
    name = Path(review["archive"])
    extension = name.suffix.lower()
    if name.name != review["archive"] or extension[1:] not in DISC_PATCH_ARCHIVES:
        raise ValueError("Invalid reviewed patch archive name")
    if not (page := review.get("archivePage")):
        return source / "translations" / RHDN_CONSOLES[platform] / "patches" / name
    downloaded = root / "sources" / name
    if downloaded.is_file():
        return downloaded
    cached = root / "patches" / f"{review['archiveSha256']}{extension}"
    if cached.is_file():
        return cached
    raise ValueError(f"Download {page} to {downloaded}")


def _publish_project(root, archive, review, title, signature, files, rom_root, metadata):
    plan = review["discs"]
    with TemporaryDirectory(dir=root, prefix=".build-") as directory:
        work = Path(directory)
        local_patch = work / f"patch{archive.suffix.lower()}"
        copyfile(archive, local_patch)
        if _digest(local_patch, "sha256") != review["archiveSha256"]:
            raise ValueError("The source patch archive checksum changed")
        patches = _extract_patches(local_patch, plan, work)
        translated = work / "translated.zip"
        with ZipFile(translated, "w", compression=ZIP_DEFLATED, compresslevel=1) as bundle:
            cues = [_build_disc(bundle, files[signature, disc["archiveName"]], disc, patches, work, rom_root)
                    for disc in plan]
            if len(cues) > 1:
                with bundle.open("Play.m3u", "w") as playlist:
                    playlist.write(("\n".join(cues) + "\n").encode("utf-8"))
        disc_set = _store_artifact(root / "discs", translated, _digest(translated, "sha256"))
        patch = _store_artifact(root / "patches", local_patch, review["archiveSha256"])
    tag = " ".join(item for item in (metadata["language"], metadata["version"]) if item)
    filename = re.sub(r'[/\\\x00-\x1f\x7f]', "_", f"{title} [{tag}].zip")
    fingerprint = f"disc-set\0{signature}\0{patch['sha256']}\0{disc_set['sha256']}"
    return {
        **metadata, **patch, "key": sha256(fingerprint.encode()).hexdigest(), "signatures": [signature],
        "format": archive.suffix.lower()[1:], "filename": re.sub(r"^\[\d+\]", "", review["archive"]),
        "layout": DISC_LAYOUT, "evidence": review.get("evidence", "verified-disc-build"),
        "baseDiscs": [{key: disc[key] for key in ("archiveName", "inputSha1", "outputSha1")} for disc in plan],
        "discSet": {**disc_set, "filename": filename},
    }


def sync_disc_translations(source, root, rom_root, *, platform, report=None):
    if which("xdelta3") is None:
        raise ValueError("xdelta3 is required to build reviewed disc translations")
    review_path = PROJECT_ROOT / "reference" / f"{platform}_translation_reviews.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8"))["projects"]
    console_keys = {row["consolekey"]: row["consoleid"] for row in _dump_rows(source, "console")}
    console = console_keys[RHDN_CONSOLES[platform]]
    rows = {str(row["transkey"]): row for row in _dump_rows(source, "transdata") if row["consolekey"] == console}
    languages = {row["id"]: unescape(row["name"]) for row in _dump_rows(source, "language")}
    statuses = {row["id"]: row["description"] for row in _dump_rows(source, "patchstatus")}
    selected = [rows[key] for key in reviews if key in rows]
    authors = _translation_authors(source, selected)

    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            bases, files = _reviewed_bases(connection, platform, reviews)
    finally:
        engine.dispose()
    root.mkdir(parents=True, exist_ok=True)
    records, failures = [], {}
    for project, review in reviews.items():
        try:
            row = rows[project]
            names = tuple(disc["archiveName"] for disc in review["discs"])
            if len(matches := bases.get(names, {})) != 1:
                raise ValueError("The reviewed disc set is unavailable or ambiguous")
            (signature, title), = matches.items()
            archive = _project_archive(source, root, platform, review)
            metadata = {
                "rhdnId": row["transkey"], "title": title, "language": languages[row["language"]],
                "authors": review.get("authors", authors.get(row["transkey"], [])),
                "version": review.get("version", unescape(row["patchver"] or "").strip()),
                "status": statuses[row["patchstatus"]],
                "releasedAt": review.get("releasedAt", row["patchrel_unix"] or 0),
            }
            if source_url := review.get("sourceUrl"):
                metadata["sourceUrl"] = source_url
            records.append(_publish_project(root, archive, review, title, signature, files, rom_root, metadata))
        except (ArchiveError, BadZipFile, KeyError, NotImplementedError, OSError, RuntimeError, ValueError) as error:
            failures[project] = str(error)

    records.sort(key=translation_order)
    summary = {"sourceRecords": len(rows), "reviewedProjects": len(reviews), "matchedProjects": len(records),
               "discDownloads": len(records), "patchedDiscs": sum(len(record["baseDiscs"]) for record in records),
               "languages": dict(Counter(record["language"] for record in records)),
               "failures": failures}
    if report is not None:
        write_report(report, {"summary": summary, "translations": records})
    if not records:
        raise ValueError(f"No reviewed disc translations could be built: {failures}")
    write_report(root / INDEX_NAME, {"version": INDEX_VERSION, "translations": records})
    return summary
