"""Match scanned PC Engine and TurboGrafx-16 manuals to a HuCard release."""

from collections import defaultdict
import json
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from gamedb.catalog.megadrive_media import _category_pages
from gamedb.catalog.retail_media import _manual_key, release_names
from gamedb.catalog.retail_source import cell_text


MANUAL_PROJECT = "https://www.pcemanuals.org/"
DIGITAL_PRESS = "https://www.digitpress.com/library/manuals/turbografx/index.html"
MANUAL_SHEET = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQ89VimhOIQCJ8mxmldNxhxW-Hxp2fEU1kK2ShgSV4_gDymOT6KFZIsXxwrkJFNAro_rMkf_fIIPZTS"
    "/pubhtml/sheet?gid=0&single=true"
)
ARCHIVE_ITEMS = {"ia-manuals-us.json": ("NECTurboGrafx-16Manuals", "NA"),
                 "ia-manuals-jp.json": ("NECPCEngineManuals", "JP")}
ARCHIVE_COLLECTION = "https://archive.org/advancedsearch.php?" + urlencode([
    ("q", "collection:turbografix16manuals AND mediatype:texts"), ("fl[]", "identifier"),
    ("fl[]", "title"), ("rows", 1000), ("output", "json"),
])
DIRECT_PDFS = {
    "necretro.org": "NEC Retro", "retrocdn.net": "Retro CDN", "dds.konami.com": "Konami",
    "www.pcengine.co.uk": "PC Engine Software Bible", "www.videogameden.com": "Video Game Den",
    "www.gamingalexandria.com": "Gaming Alexandria",
}
MANUAL_SOURCES = {
    **{name: f"https://archive.org/metadata/{item}" for name, (item, _) in ARCHIVE_ITEMS.items()},
    "ia-manuals-index.json": ARCHIVE_COLLECTION,
    "manual-sheet-rows.html": MANUAL_SHEET,
    "digitpress-tg16.html": DIGITAL_PRESS,
}
REGION_TAGS = {"JP": "JP", "J": "JP", "Japan": "JP", "US": "NA", "U": "NA", "USA": "NA"}
UNRELATED = re.compile(r"\b(?:CD-ROM|TurboGrafx-CD|SuperGrafx|quick reference|poster|advertisement|hint book)\b", re.I)
NEC_RETRO_CATEGORIES = {"JP": "PC Engine JP manual scans", "NA": "TurboGrafx-16 US manual scans"}


def nec_retro_scans(directory):
    scans, warnings = [], []
    for market, category in NEC_RETRO_CATEGORIES.items():
        try:
            pages = list(_category_pages(directory, category, site="https://necretro.org"))
        except (OSError, ValueError) as error:
            warnings.append(f"{category}: {error}")
        else:
            scans.extend((market, source, items) for source, items in pages)
    return scans, warnings


def _sheet_manuals(content):
    soup = BeautifulSoup(content, "html.parser")
    for row in soup.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6 or not (link := cells[3].find("a", href=True)):
            continue
        names = [cell_text(cell) for cell in cells[:2] if cell_text(cell)]
        location = urlsplit(link["href"])
        if location.hostname == "www.google.com" and location.path == "/url":
            location = urlsplit(parse_qs(location.query).get("q", [""])[0])
        host, path = location.hostname, location.path
        if host in DIRECT_PDFS and path.casefold().endswith(".pdf"):
            source = DIRECT_PDFS[host]
        elif host == "archive.org" and re.fullmatch(r"/(?:details|download)/[A-Za-z0-9._-]+(?:/[^?#]+)?", path):
            source = "Internet Archive"
        else:
            continue
        if location.scheme not in {"http", "https"} or UNRELATED.search(" ".join(names + [path])):
            continue
        destination = urlunsplit(("https", host, path, "", ""))
        dpi = cell_text(cells[4])
        yield names, "JP", (2, int(dpi) if dpi.isdecimal() else 0), {
            "url": destination, "source": source, "sourceUrl": MANUAL_PROJECT,
        }


def _archive_item_manuals(content, item, market):
    metadata = json.loads(content)
    if metadata.get("metadata", {}).get("identifier") != item:
        raise ValueError(f"Unexpected manual archive {item}")
    for file in metadata.get("files", ()):
        name = file["name"]
        if (not name.lower().endswith(".pdf") or file.get("source") != "original"
                or file.get("private") in ("true", True) or UNRELATED.search(name)):
            continue
        title = PurePosixPath(name).stem.replace("_", " ")
        title = re.sub(r"\s*\((?:USA|Japan)\)\s*$", "", title)
        yield [title], market, (3, 0), {
            "url": f"https://archive.org/download/{item}/{quote(name, safe='')}",
            "source": "Internet Archive",
            "sourceUrl": f"https://archive.org/details/{item}",
            "sha1": file.get("sha1"),
            "size": int(file["size"]),
        }


def _archive_collection_manuals(content):
    listing = json.loads(content)["response"]
    if len(listing["docs"]) != listing["numFound"]:
        raise ValueError("Incomplete TurboGrafx-16 manual index")
    for entry in listing["docs"]:
        title = entry.get("title", "")
        if UNRELATED.search(title):
            continue
        regions = {REGION_TAGS[region] for region in re.findall(r"\(([^()]*)\)", title) if region in REGION_TAGS}
        if len(regions) != 1:
            continue
        name = re.split(r"\s+(?:\[(?:[A-Za-z0-9 -]+)\]|\([^()]+\))", title, maxsplit=1)[0]
        if not name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]+", entry["identifier"]):
            continue
        url = f"https://archive.org/details/{entry['identifier']}"
        yield [name], regions.pop(), (1, 0), {"url": url, "source": "Internet Archive", "sourceUrl": url}


def _digital_press_manuals(content):
    for row in BeautifulSoup(content, "html.parser").find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 2 or not (link := cells[1].find("a", href=True)):
            continue
        if not re.fullmatch(r"[^/]+\.pdf", link["href"], re.I):
            continue
        yield [cell_text(cells[0])], "NA", (1, 1), {
            "url": urljoin(DIGITAL_PRESS, quote(link["href"])), "source": "Digital Press", "sourceUrl": DIGITAL_PRESS,
        }


def _nec_retro_manuals(scans):
    for market, _, items in scans:
        for item in items.values():
            image = next(iter(item.get("imageinfo", ())), {})
            url = image.get("url", "")
            location = urlsplit(url)
            if (image.get("mime") != "application/pdf" or location.scheme != "https"
                    or location.hostname not in {"necretro.org", "retrocdn.net"} or UNRELATED.search(item["title"])):
                continue
            names = [use["title"] for use in item.get("fileusage", ())]
            if names:
                yield names, market, (1, 2), {
                    "url": url, "source": "NEC Retro", "sourceUrl": image["descriptionurl"],
                    "sha1": image.get("sha1"), "size": image.get("size"),
                }


def add_manuals(catalog, indexes, reference, scans=()):
    releases, claims = {}, defaultdict(set)
    aliases = defaultdict(list)
    for alias in reference.get("archiveAliases", ()):
        aliases[alias["edition"], alias["market"]].append(alias["archiveTitle"])
    for game in catalog["games"]:
        for release in game["releases"]:
            market, edition = release["market"], release["edition"]
            releases[edition, market] = release
            names = [*release_names(release), *aliases[edition, market]]
            names.extend(reference.get("manualTitles", {}).get(edition, ()))
            if sum(other["market"] == market for other in game["releases"]) == 1:
                names.extend(alias["title"] for alias in game["aliases"] if market in alias["regions"])
            for name in names:
                claims[market, _manual_key(name)].add((edition, market))

    candidates = list(_nec_retro_manuals(scans))
    for filename, (item, market) in ARCHIVE_ITEMS.items():
        if filename in indexes:
            candidates.extend(_archive_item_manuals(indexes[filename].content, item, market))
    if sheet := indexes.get("manual-sheet-rows.html"):
        candidates.extend(_sheet_manuals(sheet.content))
    if archive := indexes.get("ia-manuals-index.json"):
        candidates.extend(_archive_collection_manuals(archive.content))
    if press := indexes.get("digitpress-tg16.html"):
        candidates.extend(_digital_press_manuals(press.content))
    unavailable = set(reference.get("unavailableManuals", ()))
    choices = {}
    for names, market, rank, manual in candidates:
        if manual["url"] in unavailable:
            continue
        keys = set().union(*(claims[market, _manual_key(name)] for name in names))
        if len(keys) != 1:
            continue
        (key,) = keys
        rank = (*rank, manual["url"])
        if key not in choices or rank > choices[key][0]:
            choices[key] = (rank, manual)
    for manual in reference.get("manuals", ()):
        key = manual["edition"], manual["market"]
        if key not in releases:
            raise ValueError(f"Invalid reviewed HuCard manual for {key}")
        choices[key] = ((4, 0, manual["url"]), {field: value for field, value in manual.items()
                                              if field not in {"edition", "market"}})
    for key, release in releases.items():
        if key in choices:
            _, manual = choices[key]
            release["manuals"] = [{
                "name": release["titles"][0], "regions": ["JP" if release["market"] == "JP" else "US"], "format": "PDF",
                **manual,
            }]
