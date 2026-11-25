"""Read Master System release and manual references from preservation indexes."""

from collections import defaultdict
import json
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from gamedb.catalog.retail_media import _manual_key, release_names
from gamedb.catalog.retail_source import cell_text
from gamedb.config import PROJECT_ROOT


SMS_POWER = "https://www.smspower.org"
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/mastersystem-retail"
GAME_INDEX = SMS_POWER + "/Games/SMS"
MANUAL_INDEX = "https://archive.org/advancedsearch.php?" + urlencode([
    ("q", "collection:sega_master_system_manuals AND mediatype:texts"),
    ("fl[]", "identifier"), ("fl[]", "title"), ("rows", "1000"), ("output", "json"),
])
MANUAL_REGIONS = {
    "J": ("JP", "JP"), "JP": ("JP", "JP"), "U": ("US", "NA"), "US": ("US", "NA"),
    "CA": ("CA", "NA"), "E": ("EU", "PAL"), "EU": ("EU", "PAL"), "UK": ("UK", "PAL"),
    "AU": ("AU", "PAL"), "BR": ("BR", "BR"), "PT": ("PT", "PAL"),
    **{region: (region, "PAL") for region in ("DE", "ES", "FR", "IT", "NL", "SE", "NO", "GR", "FI", "DK")},
}


def sms_power_matches(catalog, content, overrides):
    """Use exact names and require both the title and source page to have a single owner."""
    names, records = defaultdict(set), {}
    soup = BeautifulSoup(content, "html.parser")
    for row in soup.find_all("tr"):
        if len(cells := row.find_all("td", recursive=False)) != 4:
            continue
        link = cells[1].find("a", href=re.compile(r"^/Games/[A-Za-z0-9.-]+-SMS$"))
        if not link:
            continue
        path = link["href"]
        title = cell_text(cells[1]).partition(" - see ")[0]
        for name in [cell_text(link), *title.split(" / ")]:
            if name:
                names[_manual_key(name)].add(path)
        record = records.setdefault(path, {"regions": set(), "genres": set()})
        record["regions"].update(image["alt"] for image in cells[2].find_all("img", alt=True) if image["alt"])
        record["genres"].update(image["alt"] for image in cells[3].find_all("img", alt=True) if image["alt"])

    claims, owners = {}, defaultdict(set)
    for game in catalog["games"]:
        if path := overrides.get(game["title"]):
            if path not in records:
                continue
            paths = {path}
        else:
            base_releases = [release for release in game["releases"] if release["edition"] == game["title"]]
            variants = {title for release in game["releases"] if release["edition"] != game["title"]
                        for title in release["titles"]}
            titles = [game["title"], *(alias["title"] for alias in game["aliases"] if alias["title"] not in variants),
                      *(name for release in base_releases for name in release_names(release))]
            paths = set().union(*(names[_manual_key(name)] for name in titles))
        if len(paths) == 1:
            (path,) = paths
            claims[game["key"]] = path
            owners[path].add(game["key"])
    return {
        key: {"url": urljoin(SMS_POWER, path), **records[path]} for key, path in claims.items()
        if owners[path] == {key}
    }


def add_archive_manuals(catalog, content, aliases=(), *, reviewed=None):
    """Fill gaps using cataloged scans with a single title and matching packaging region."""
    data = json.loads(content)["response"]
    if data["numFound"] != len(data["docs"]):
        raise ValueError("Incomplete Internet Archive Master System manual index")

    releases, claims = {}, defaultdict(set)
    approved_names = defaultdict(list)
    for alias in aliases:
        approved_names[alias["edition"], alias["market"]].append(alias["archiveTitle"])
    for game in catalog["games"]:
        for release in game["releases"]:
            key, market = release["key"], release["market"]
            releases[key] = release
            titles = [*release_names(release), *approved_names[release["edition"], market]]
            titles.extend((reviewed or {}).get(release["edition"], ()))
            for title in titles:
                claims[market, _manual_key(title)].add(key)

    manuals = defaultdict(list)
    for item in data["docs"]:
        title = item.get("title", "")
        match = re.fullmatch(r"(.*?)\s*\((?:19|20)[0-9xX]{2}\)\(([^()]+)\)(.*)", title)
        if not match or not (region_market := MANUAL_REGIONS.get(match[2].upper())):
            continue
        name, note = match[1], match[3]
        if re.search(r"\b(?:map|hints?|quick reference|poster|box|cart|advertisement|guide|prototype)\b", note, re.I):
            continue
        region, market = region_market
        keys = claims[market, _manual_key(name)]
        if len(keys) != 1:
            continue
        (key,) = keys
        if releases[key].get("manuals"):
            continue
        identifier = item["identifier"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]+", identifier):
            continue
        url = f"https://archive.org/details/{identifier}"
        manual = {
            "name": releases[key]["titles"][0], "regions": [region], "format": "PDF",
            "url": url, "source": "Internet Archive", "sourceUrl": url,
        }
        # Prefer market-wide English scans over country variants when both are available.
        rank = (region in {"US", "JP", "EU", "BR"}, not note, identifier)
        manuals[key].append((rank, manual))
    for key, choices in manuals.items():
        releases[key]["manuals"] = [max(choices, key=lambda item: item[0])[1]]


def add_reviewed_artwork(catalog, scans):
    releases = {(release["edition"], release["market"]): release
                for game in catalog["games"] for release in game["releases"]}
    for scan in scans:
        for market in scan["markets"]:
            release = releases[scan["edition"], market]
            artwork = release.setdefault("artwork", {})
            if scan.get("preferred") or scan["kind"] not in artwork:
                artwork[scan["kind"]] = {
                    "url": f"{SMS_POWER}/uploads/{scan['file']}",
                    "source": {"name": "SMS Power!", "url": f"{SMS_POWER}/{scan['page']}"},
                    "basis": "reviewed-scan",
                }
