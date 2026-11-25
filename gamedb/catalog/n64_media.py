"""Match original Nintendo 64 manual scans to their regional Game Paks."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from hashlib import sha256
from io import StringIO
import json
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from gamedb.catalog.references import read_index
from gamedb.catalog.retail_media import _archive_link, _manual_key, release_names
from gamedb.catalog.retail_source import cell_text


PEEBS_N64 = "https://sites.google.com/view/n64manuals"
EMULATION64 = "https://www.emulation64.fr/?page=notices"
ARCHIVES = {"ia-na-manuals.json": ("N64Manuals", "NA"), "ia-manuals.json": ("Nintendo64GameManuals", None)}
MANUAL_SOURCES = {
    **{filename: f"https://archive.org/metadata/{item}" for filename, (item, _) in ARCHIVES.items()},
    "peebs-n64-sheet.csv": ("https://docs.google.com/spreadsheets/d/11Vfmz3ySudOoBCh4z4VeSfEwyXMjeVVGCOoRFUve9Bg/"
                           "gviz/tq?tqx=out:csv"),
    "emulation64.html": EMULATION64,
}
REGIONS = {
    **dict.fromkeys(("J", "JP", "JAP", "JPN", "JAPAN"), "JP"),
    **dict.fromkeys(("U", "NA", "US", "USA", "CAN"), "NA"),
    **dict.fromkeys(("A", "AU", "AUS", "E", "EU", "EUR", "PAL", "EUROPE", "EUROPEAN", "UK", "GBR", "GB", "FRA",
                     "FRANCE", "GER", "ALL", "DEU", "ESP", "ITA", "HOL", "NLD"), "PAL"),
    **dict.fromkeys(("BR", "BRA", "BRAZIL"), "BR"),
}
UNRELATED = re.compile(
    r"\b(?:operation card|quick reference|guide|traduction|fan translation|supplement|addendum|poster|box art|controller pak)\b",
    re.I,
)
REGION_TAG = re.compile(r"\(([^()]+)\)|[-_](\w+)(?=[-_.]|$)")


def _market(name):
    regions = {REGIONS[code] for parenthesized, slug in REGION_TAG.findall(name)
               if (code := (parenthesized or slug).upper()) in REGIONS}
    return regions.pop() if len(regions) == 1 else None


def _album_name(filename):
    name = PurePosixPath(filename).stem.replace("_", " ")
    name = re.split(r"\s+-\s+(?:19|20)\d{2}\s+-\s+", name, maxsplit=1)[0]
    name = re.sub(r"\s*-\s*(?:[A-Z]{2,3}\s+)?Manual\s*-\s*N64$", "", name, flags=re.I)
    if match := re.search(r"\s*\(([^()]+)\)(?:\s*\([A-Za-z,]+\))?$", name):
        if match[1].upper() in REGIONS:
            name = name[:match.start()]
    return name


def _archive_manuals(content, item, default_market):
    metadata = json.loads(content)
    if metadata.get("metadata", {}).get("identifier") != item:
        raise ValueError(f"Unexpected Nintendo 64 manual collection {item}")
    for file in metadata.get("files", ()):
        name = file["name"]
        if (not name.lower().endswith(".pdf") or file.get("source") != "original"
                or file.get("private") in (True, "true") or UNRELATED.search(name)):
            continue
        market = default_market or _market(name)
        if market:
            yield _album_name(name), market, 3 if default_market else 2, {
                "url": f"https://archive.org/download/{item}/{quote(name, safe='')}",
                "source": "Spoonman’s N64 Manual Archive" if default_market else "Internet Archive",
                "sourceUrl": f"https://archive.org/details/{item}", "sha1": file.get("sha1"), "size": int(file["size"]),
            }


def _peebs_manuals(content):
    for row in csv.reader(StringIO(content.decode("utf-8-sig"))):
        if len(row) != 2 or not (url := _archive_link(row[1])) or UNRELATED.search(row[0]):
            continue
        path = urlsplit(url).path
        market = _market(unquote(path).replace("/", " "))
        if path.startswith("/details/Nintendo64Manuals_201812/"):
            file = unquote(path.split("/", 3)[-1])
            if not file.casefold().endswith(".pdf"):
                file += ".pdf"
            url = "https://archive.org/download/Nintendo64Manuals_201812/" + quote(file, safe="")
        yield row[0], market, 1, {"url": url, "source": "Peebs’ N64 Manual Archive", "sourceUrl": PEEBS_N64}


def _listing_ids(index):
    soup = BeautifulSoup(index.content, "html.parser")
    for anchor in soup.select('a[href^="?page=notices"]'):
        query = parse_qs(urlsplit(anchor["href"]).query)
        if query.get("page") == ["notices"] and query.get("id") and not UNRELATED.search(cell_text(anchor)):
            yield query["id"][0]


def _emulation_scans(directory, index):
    def read(title):
        url = f"{EMULATION64}&{urlencode({'id': title})}"
        filename = sha256(title.encode()).hexdigest()[:24] + ".html"
        try:
            source = read_index(directory / "emulation64" / filename, url, max_bytes=2_000_000)
        except (OSError, ValueError) as error:
            return [], f"{title}: {error}"
        manuals = []
        for link in BeautifulSoup(source.content, "html.parser").select('a[href^="pdf/"]'):
            path = urlsplit(link["href"])
            if not cell_text(link).startswith("Télécharger la Notice") or path.fragment or path.query:
                continue
            flag = link.find_previous("img", src=re.compile(r"^design/[A-Z]{2,3}\.jpg$"))
            market = REGIONS.get(PurePosixPath(flag["src"]).stem) if flag else None
            file = unquote(path.path)
            if not market or not file.startswith("pdf/N64 - ") or not file.endswith(".pdf") or UNRELATED.search(file):
                continue
            name = re.sub(r"\s*\([^()]+\)(?:\s*\(\d+\))?$", "", PurePosixPath(file).stem.removeprefix("N64 - "))
            manuals.append((name, market, 2, {"url": urljoin(EMULATION64, quote(file, safe="/")),
                                             "source": "Emulation64.fr", "sourceUrl": url}))
        return manuals, None

    manuals, warnings = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for candidates, warning in pool.map(read, sorted(set(_listing_ids(index)))):
            manuals.extend(candidates)
            if warning:
                warnings.append(warning)
    return manuals, warnings


def add_manuals(catalog, indexes, reference, directory):
    releases, claims = {}, defaultdict(set)
    for game in catalog["games"]:
        for release in game["releases"]:
            market, edition = release["market"], release["edition"]
            releases[edition, market] = release
            names = {edition, *release_names(release)}
            names.update(reference.get("manualTitles", {}).get(edition, ()))
            for name in names:
                claims[market, _manual_key(name)].add((edition, market))

    candidates, warnings = [], []
    for filename, (item, market) in ARCHIVES.items():
        if filename in indexes:
            candidates.extend(_archive_manuals(indexes[filename].content, item, market))
    if spreadsheet := indexes.get("peebs-n64-sheet.csv"):
        candidates.extend(_peebs_manuals(spreadsheet.content))
    if scan_index := indexes.get("emulation64.html"):
        scans, warnings = _emulation_scans(directory, scan_index)
        candidates.extend(scans)

    choices = {}
    unavailable = set(reference.get("unavailableManuals", ()))
    for name, market, rank, manual in candidates:
        if manual["url"] in unavailable:
            continue
        identity = _manual_key(name)
        keys = claims[market, identity] if market else claims["NA", identity] | claims["PAL", identity]
        if len(keys) != 1:
            continue
        (key,) = keys
        priority = (rank, manual["url"])
        if key not in choices or priority > choices[key][0]:
            choices[key] = (priority, manual)
    for manual in reference.get("manuals", ()):
        key = manual["edition"], manual["market"]
        if key not in releases:
            raise ValueError(f"Unknown reviewed Nintendo 64 manual release {key}")
        choices[key] = ((4, manual["url"]), {field: value for field, value in manual.items()
                                             if field not in {"edition", "market"}})
    for key, (_, manual) in choices.items():
        release = releases[key]
        release["manuals"] = [{"name": release["titles"][0], "regions": [key[1]], "format": "PDF", **manual}]
    return warnings


def add_reviewed_artwork(catalog, scans):
    releases = {(release["edition"], release["market"]): release
                for game in catalog["games"] for release in game["releases"]}
    for scan in scans:
        release = releases[scan["edition"], scan["market"]]
        release.setdefault("artwork", {})[scan["kind"]] = {
            "url": scan["url"], "source": scan["source"], "regions": scan["regions"], "basis": "reviewed-scan",
        }
