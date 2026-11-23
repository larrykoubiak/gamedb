"""Use checksum-linked region metadata from the Rx2.0 manual restoration project."""

from collections import defaultdict
from contextlib import closing
from hashlib import sha1
import json
from pathlib import Path, PurePosixPath
import sqlite3
import struct
from tempfile import NamedTemporaryFile
from urllib.parse import quote
from urllib.request import Request, urlopen

from gamedb.catalog.references import SourceIndex, read_index
from gamedb.catalog.retail import _compact_title
from gamedb.catalog.retail_media import release_names


PDF_ITEM = "rx2MRPnes1250pxPDF"
CALIBRE_ITEM = "Rx2MRPnesCalibre"
ARCHIVE = "https://archive.org"
MANUAL_MARKETS = {"(1.1) US Licensed": "NA", "(1.2) US Unlicensed": "NA", "(1.4) Europe": "PAL", "(1.5) Japan": "JP"}
LANGUAGES = {"eng": "English", "jpn": "Japanese", "fra": "French", "deu": "German", "ita": "Italian",
             "spa": "Spanish", "nld": "Dutch", "por": "Portuguese", "swe": "Swedish", "fin": "Finnish"}
EXPORT_TRAILER = struct.Struct("!QII?")


def _download_url(item, name):
    return f"{ARCHIVE}/download/{item}/{quote(name)}"


def _calibre_metadata(directory, collection):
    files = {PurePosixPath(row["name"]).name: row for row in json.loads(collection.content)["files"]
             if row.get("source") == "original" and row["name"].endswith(".calibre-data")}
    last = files["part-0008.calibre-data"]
    end = read_index(directory / "rx2-calibre-end.bin", _download_url(CALIBRE_ITEM, last["name"]), max_bytes=1024**2)
    if sha1(end.content).hexdigest() != last["sha1"] or len(end.content) < EXPORT_TRAILER.size:
        raise ValueError("Rx2.0 Calibre inventory checksum changed")
    size, part, version, last_part = EXPORT_TRAILER.unpack_from(end.content, len(end.content) - EXPORT_TRAILER.size)
    if part != 8 or version != 1 or not last_part or not 0 < size <= len(end.content) - EXPORT_TRAILER.size:
        raise ValueError("Unexpected Rx2.0 Calibre inventory format")
    metadata = json.loads(end.content[-EXPORT_TRAILER.size - size:-EXPORT_TRAILER.size])
    (library_key,) = metadata["libraries"]
    library = metadata[library_key]
    entries = metadata["file_metadata"]
    part, start, length, digest, _ = entries[library["metadata.db"]]
    file = files[f"part-{part:04d}.calibre-data"]
    if start < 0 or not 0 < length <= 12 * 1024**2 or start + length >= int(file["size"]):
        raise ValueError("Unexpected Rx2.0 Calibre database size or offset")
    url = _download_url(CALIBRE_ITEM, file["name"])
    path = directory / "rx2-calibre-metadata.db"
    if path.is_file() and path.stat().st_size == length:
        content = path.read_bytes()
        if sha1(content).hexdigest() == digest:
            return end, SourceIndex(url, content), library["format_data"], entries
    request = Request(url, headers={"User-Agent": "GameDB/2.0 (NES manual inventory)",
                                   "Range": f"bytes={start}-{start + length - 1}"})
    with urlopen(request, timeout=45) as response:
        if (response.status != 206
                or response.headers.get("Content-Range") != f"bytes {start}-{start + length - 1}/{file['size']}"):
            raise ValueError("The archive did not return the requested Calibre range")
        content = response.read(length + 1)
    if len(content) != length or sha1(content).hexdigest() != digest:
        raise ValueError("Rx2.0 Calibre metadata checksum changed")
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return end, SourceIndex(url, content), library["format_data"], entries


def _book_rows(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
        database.execute("PRAGMA trusted_schema = OFF")
        columns = dict(database.execute("SELECT id, label FROM custom_columns"))
        expected = {10: "console", 11: "gamecategory", 12: "specialstatus", 13: "ratingstatus"}
        if any(columns.get(column) != label for column, label in expected.items()):
            raise ValueError("Unexpected Rx2.0 Calibre metadata columns")
        yield from database.execute("""
            SELECT book.id, book.title, console.value, category.value,
                   group_concat(DISTINCT language.lang_code),
                   (EXISTS (SELECT 1 FROM books_custom_column_12_link WHERE book=book.id)
                    OR EXISTS (SELECT 1 FROM books_custom_column_13_link WHERE book=book.id)) AS incomplete
            FROM books AS book
            JOIN books_custom_column_10_link platform ON platform.book=book.id
            JOIN custom_column_10 console ON console.id=platform.value
            JOIN books_custom_column_11_link classification ON classification.book=book.id
            JOIN custom_column_11 category ON category.id=classification.value
            LEFT JOIN books_languages_link language_link ON language_link.book=book.id
            LEFT JOIN languages language ON language.id=language_link.lang_code
            GROUP BY book.id, book.title, console.value, category.value
        """)


def manual_inventory(directory):
    pdfs = read_index(directory / "rx2-manuals.json", f"{ARCHIVE}/metadata/{PDF_ITEM}")
    collection = read_index(directory / "rx2-calibre.json", f"{ARCHIVE}/metadata/{CALIBRE_ITEM}")
    end, database, formats, entries = _calibre_metadata(directory, collection)
    files = {row["sha1"]: row for row in json.loads(pdfs.content)["files"]
             if row.get("source") == "original" and not row.get("private") and row["name"].lower().endswith(".pdf")}
    scans = []
    for book, title, console, category, languages, incomplete in _book_rows(directory / "rx2-calibre-metadata.db"):
        if incomplete or console not in {"Family Computer (Famicom)", "Nintendo Entertainment System"}:
            continue
        market = MANUAL_MARKETS.get(category)
        codes = (languages or "").split(",")
        if not market and console == "Family Computer (Famicom)" and category == "(2) Translated" and codes == ["jpn"]:
            market = "JP"
        if not market and category not in {"(1.3) Zapper Games", "(5) Requres Alternate Controller"}:
            continue
        record = formats.get(str(book), {}).get("PDF")
        if record and (file := files.get(entries[record][3])):
            scans.append((title, market, codes, file))
    return scans, (pdfs, collection, end, database)


def add_manuals(catalog, scans, aliases=()):
    releases = {}
    claims = defaultdict(set)
    for game in catalog["games"]:
        for release in game["releases"]:
            key = (release["edition"], release["market"])
            releases[key] = release
            for name in {game["title"], *release_names(release)}:
                claims[_compact_title(name)].add(key)
    for alias in aliases:
        claims[_compact_title(alias["archiveTitle"])].add((alias["edition"], alias["market"]))

    for title, market, languages, file in scans:
        keys = set().union(*(claims[_compact_title(name)] for name in (title, PurePosixPath(file["name"]).stem)))
        if market:
            keys = {key for key in keys if key[1] == market}
        if len(keys) != 1:
            continue
        (key,) = keys
        release = releases[key]
        manual = {
            "name": title, "url": _download_url(PDF_ITEM, file["name"]), "format": "PDF",
            "source": "Rx2.0 Manual Restoration Project", "sourceUrl": f"{ARCHIVE}/details/{PDF_ITEM}/",
            "regions": [key[1]], "size": int(file["size"]), "sha1": file["sha1"],
        }
        if names := [LANGUAGES[code] for code in languages if code in LANGUAGES]:
            manual["language"] = ", ".join(names)
        release.setdefault("manuals", []).append(manual)
