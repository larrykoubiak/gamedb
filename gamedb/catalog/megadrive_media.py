"""Select region-specific Mega Drive scans from Sega Retro and Digital Press."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import PurePosixPath
import re
from urllib.parse import quote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from gamedb.catalog.retail import _compact_title
from gamedb.catalog.retail_media import release_names
from gamedb.catalog.references import read_index


SEGA_RETRO = "https://segaretro.org"
DIGITAL_PRESS = "https://www.digitpress.com/library/manuals/genesis/index.html"
SCAN_MARKETS = {
    "US": "NA", "CA": "NA", "JP": "JP", "BR": "BR", "KR": "KR", "AS": "AS", "HK": "AS",
    **dict.fromkeys(("EU", "UK", "AU", "DE", "ES", "FR", "IT", "NL", "PT", "SE"), "PAL"),
}
SCAN_CATEGORY = {
    **{f"Mega Drive {country} manual scans": ("manual", country) for country in SCAN_MARKETS},
    **{f"Mega Drive {country} box scans": ("boxart", country)
       for country in ("US", "JP", "EU", "UK", "BR", "KR", "AS")},
    "Mega Drive Mini digital manuals": ("mini", None),
    "Mega Drive Mini 2 digital manuals": ("mini", None),
}
SCAN_EXCLUSIONS = re.compile(
    r"\b(?:prototype|bootleg|unlicensed|repro|rental|retro-bit|limited run|sample|advertisement)\b", re.I,
)
PACKAGING_DETAIL = re.compile(r"\b(?:backcover|back|spine|top|bottom|side|photograph)\b", re.I)
MINI_REGION = re.compile(r"\bMD ([A-Z]{2}) MDMini2? manual\b", re.I)


def _category_pages(directory, category):
    arguments = {
        "action": "query", "generator": "categorymembers", "gcmtitle": f"Category:{category}",
        "gcmtype": "file", "gcmlimit": 100, "prop": "imageinfo|fileusage",
        "iiprop": "url|mime|size|sha1", "funamespace": 0, "fulimit": 500, "format": "json",
    }
    continuation = {}
    folder = "segaretro-" + category.casefold().replace(" ", "-")
    for page in range(1, 101):
        url = f"{SEGA_RETRO}/api.php?{urlencode(arguments | continuation)}"
        source = read_index(directory / folder / f"{page}.json", url)
        payload = json.loads(source.content)
        if "error" in payload:
            raise ValueError(f"Sega Retro rejected {category}")
        yield source, payload.get("query", {}).get("pages", {})
        continuation = payload.get("continue")
        if not continuation:
            return
    raise ValueError(f"Too many pages for {category}")


def sega_retro_scans(directory):
    def fetch(category):
        try:
            files, sources = {}, []
            for source, pages in _category_pages(directory, category):
                sources.append(source)
                for key, item in pages.items():
                    entry = files.setdefault(key, {})
                    usages = {usage["pageid"]: usage for usage in
                              (*entry.get("fileusage", ()), *item.get("fileusage", ()))}
                    entry.update(item, fileusage=list(usages.values()))
            return category, list(files.values()), sources, None
        except (OSError, ValueError) as error:
            return category, [], [], f"{category}: {error}"

    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(fetch, SCAN_CATEGORY))


def _scan_file(item, kind):
    if SCAN_EXCLUSIONS.search(item["title"]):
        return None
    image = next(iter(item.get("imageinfo", ())), {})
    url = image.get("url", "")
    location = urlsplit(url)
    if location.scheme != "https" or location.hostname != "segaretro.org" or not location.path.startswith("/images/"):
        return None
    if kind == "boxart":
        if not (image["mime"] in {"image/jpeg", "image/png"} and
                image["height"] > 0 and 0.55 <= image["width"] / image["height"] <= 2.15 and
                not PACKAGING_DETAIL.search(item["title"])):
            return None
    elif image["mime"] != "application/pdf":
        return None
    return image


def add_scans(catalog, categories, press=None, aliases=(), *, reviewed_titles=None):
    claims, by_edition = defaultdict(set), {}
    releases = {}
    for game in catalog["games"]:
        local_claims, game_claims = defaultdict(set), defaultdict(set)
        game_names = {game["title"], *(alias["title"] for alias in game["aliases"])}
        for release in game["releases"]:
            key, market = release["key"], release["market"]
            releases[key] = release
            by_edition[release["edition"], market] = key
            for label in release_names(release):
                local_claims[market, _compact_title(label)].add(key)
            for label in game_names:
                game_claims[market, _compact_title(label)].add(key)
        for scope, keys in (game_claims | local_claims).items():
            claims[scope].update(keys)
    for alias in aliases:
        if key := by_edition.get((alias["edition"], alias["market"])):
            claims[alias["market"], _compact_title(alias["archiveTitle"])].add(key)
    for (edition, market), key in by_edition.items():
        for source_title in (reviewed_titles or {}).get(edition, ()):
            claims[market, _compact_title(source_title)].add(key)

    manuals, covers = defaultdict(dict), defaultdict(list)
    for category, items, _, _ in categories:
        kind, country = SCAN_CATEGORY[category]
        for item in items:
            if kind == "mini" and not (region := MINI_REGION.search(item["title"])):
                continue
            local = region[1].upper() if kind == "mini" else country
            market = SCAN_MARKETS.get(local)
            if market is None or not (image := _scan_file(item, kind)):
                continue
            usages = item.get("fileusage", ())
            keys = {key for usage in usages for key in claims[market, _compact_title(usage["title"])]}
            if len(keys) != 1:
                continue
            (key,) = keys
            url, page = image["url"], image["descriptionurl"]
            if kind == "boxart":
                rank = (image["width"] < image["height"], image["width"] * image["height"])
                covers[key].append((rank, {
                    "url": url, "source": {"name": "Sega Retro", "url": page},
                    "regions": [local], "basis": "packaging-scan",
                }))
            else:
                release = releases[key]
                manual = {
                    "name": release["titles"][0], "regions": [local], "url": url, "sourceUrl": page,
                    "source": "Sega Retro" if kind == "manual" else "Sega via Sega Retro",
                    "format": "PDF", "sha1": image.get("sha1"), "size": image.get("size"),
                }
                rank = (kind == "manual", image.get("pagecount", 0), image.get("size", 0), url)
                if local not in manuals[key] or rank > manuals[key][local][0]:
                    manuals[key][local] = (rank, manual)
    if press:
        for link in BeautifulSoup(press.content, "html.parser").find_all("a", href=True):
            name, href = link.get_text(" ", strip=True), link["href"]
            keys = claims["NA", _compact_title(name)]
            if len(keys) != 1 or not re.fullmatch(r"[^/]+\.pdf", href, re.I):
                continue
            (key,) = keys
            manuals[key].setdefault("US", ((), {
                "name": name, "regions": ["US"], "format": "PDF",
                "url": urljoin(DIGITAL_PRESS, quote(href)), "source": "Digital Press", "sourceUrl": DIGITAL_PRESS,
            }))
    for key, options in manuals.items():
        releases[key]["manuals"] = [manual for _, manual in sorted(options.values(), key=lambda item: (
            item[1]["regions"], item[1]["url"],
        ))]
    for key, options in covers.items():
        artwork = releases[key].setdefault("artwork", {})
        artwork.setdefault("boxart", max(options, key=lambda item: (item[0], item[1]["url"]))[1])
