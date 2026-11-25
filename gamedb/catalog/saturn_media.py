"""Match Sega Saturn covers and instruction booklets to their markets."""

from collections import defaultdict
import json
import re
from urllib.parse import urlencode

from .retail_media import _manual_key, release_names


SATURN_MANUALS = "https://archive.org/details/segasaturnmanuals"
COLLECTION_URL = "https://archive.org/advancedsearch.php?" + urlencode([
    ("q", "collection:segasaturnmanuals"), ("fl[]", "identifier"), ("fl[]", "title"),
    ("rows", 2000), ("output", "json"),
])
COLLECTION_FILE = "ia-collection.json"
REGIONS = {
    **dict.fromkeys(("J", "JP", "JPN", "JAPAN"), "JP"),
    **dict.fromkeys(("U", "US", "USA", "NA"), "NA"),
    **dict.fromkeys(("E", "EU", "PAL", "UK", "FR", "FRA", "GER", "DE", "ES", "IT", "EUR", "EUROPE"), "PAL"),
    **dict.fromkeys(("BR", "BRA", "BRAZIL"), "BR"), "KR": "KR", "TW": "AS",
}
UNRELATED = re.compile(
    r"\b(?:strategy guide|quick reference|registration card|soundtrack|bonus disc|songlist|poster|map|"
    r"service manual|technical manual|lyric sheet|advertisement|controller)\b", re.I,
)


def collection_manuals(index):
    payload = json.loads(index)
    response = payload.get("response", {})
    docs = response.get("docs", [])
    if not docs or len(docs) != response.get("numFound"):
        raise ValueError("Incomplete Internet Archive Saturn manual catalog")
    for doc in docs:
        identifier = doc["identifier"]
        title = doc["title"].removeprefix("Sega Saturn Manual: ").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", identifier) or UNRELATED.search(title):
            continue
        year = re.search(r"\s*\((?:19|20)\d{2}\)", title)
        if year is None:
            continue
        notes = re.findall(r"\(([^()]+)\)", title[year.end():])
        markets = {REGIONS[note.upper()] for note in notes if note.upper() in REGIONS}
        if len(markets) != 1:
            continue
        (market,) = markets
        yield title[:year.start()].strip(), market, "color" in notes, {
            "url": f"https://archive.org/details/{identifier}", "source": "Sega Saturn Manual Archive",
            "sourceUrl": SATURN_MANUALS,
        }


def add_manuals(catalog, references, index, aliases):
    claims, releases = defaultdict(set), {}
    titles = references.get("manualTitles", {})
    alternate = defaultdict(set)
    for item in aliases:
        alternate[item["edition"], item["market"]].add(item["archiveTitle"])
    for game in catalog["games"]:
        for release in game["releases"]:
            edition, market = key = (release["edition"], release["market"])
            releases[key] = release
            names = {edition, *release_names(release), *titles.get(edition, ()), *alternate[key]}
            for name in names:
                claims[market, _manual_key(name)].add(key)

    choices = {}
    unavailable = set(references.get("unavailableManuals", ()))
    for name, market, color, manual in collection_manuals(index) if index else ():
        keys = claims[market, _manual_key(name)]
        if len(keys) != 1 or manual["url"] in unavailable:
            continue
        (key,) = keys
        rank = (color, manual["url"])
        if key not in choices or rank > choices[key][0]:
            choices[key] = rank, manual
    for scan in references.get("manuals", ()):
        key = scan["edition"], scan["market"]
        if key not in releases:
            raise ValueError(f"Unknown Sega Saturn manual release {key}")
        choices[key] = (True, scan["url"]), {field: value for field, value in scan.items()
                                             if field not in {"edition", "market"}}
    for key, (_, manual) in choices.items():
        release = releases[key]
        release["manuals"] = [{"name": release["titles"][0], "regions": [release["market"]], "format": "PDF", **manual}]


def add_reviewed_covers(catalog, covers):
    releases = {(release["edition"], release["market"]): release
                for game in catalog["games"] for release in game["releases"]}
    for cover in covers:
        key = cover["edition"], cover["market"]
        release = releases[key]
        release.setdefault("artwork", {})["boxart"] = {
            "url": cover["url"], "source": cover["source"], "regions": [cover["market"]], "basis": "reviewed-image",
        }
