"""Read the US retail checklist and edition records from Game-Rave."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from html import unescape
import json
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .references import read_index


GAME_RAVE = "https://game-rave.com/"
CHECKLIST = GAME_RAVE + "?page_id=105"
CHECKLIST_PAGES = (105, 14110, 14104, 14097, 14086)
CHECKLIST_COUNTS = (249, 267, 283, 291, 194)
POST_LINK = re.compile(r"https://(?:www\.)?game-rave\.com/\?p=(\d+)$")
FIELD = re.compile(r"^(Genre|Publisher|Developer|Released|Sony ID|CDs|Players|Memory|Accessories|ESRB):\s*(.*)", re.I)
SERIAL = re.compile(r"\b(?:(SCUS|SLUS)[-\s]*)?(\d{5})[A-Z]{0,2}\b", re.I)
RATING_NAMES = {"Kids to Adult": "Kids to Adults", "Everybody": "Everyone"}


def game_title(label):
    label = " ".join(unescape(label).split())
    label = re.sub(r" \((?:Black Label SCUS|GH is SLUS)\)$", "", label)
    return re.sub(r"^(.+), (The|An|A)(?=$|:| - | – )", r"\2 \1", label, flags=re.I)


def serials(value):
    codes = []
    prefix = None
    for match in SERIAL.finditer(value):
        prefix = match[1].upper() if match[1] else prefix
        if prefix:
            codes.append(f"{prefix}-{match[2]}")
    return list(dict.fromkeys(codes))


def _key(*parts):
    return sha256("\0".join(("gamedb:playstation-retail", *parts)).encode()).hexdigest()[:32]


def _checklist_labels(indexes):
    titles = defaultdict(list)
    for index, count in zip(indexes, CHECKLIST_COUNTS, strict=True):
        page = BeautifulSoup(index.content, "html.parser")
        links = [(int(match[1]), game_title(a.get_text(" ", strip=True)))
                 for a in page.select(".entry-content a[href]")
                 if (match := POST_LINK.fullmatch(a["href"])) and a.get_text(strip=True)]
        if len(links) != count:
            raise ValueError(f"Unexpected number of retail games in {index.url}: {len(links)}")
        for post, title in links:
            if title not in titles[post]:
                titles[post].append(title)
    return titles


def _post_batch(directory, ids):
    url = GAME_RAVE + "?" + urlencode({
        "rest_route": "/wp/v2/posts", "include": ",".join(map(str, ids)),
        "per_page": len(ids), "_fields": "id,link,title,content",
    })
    index = read_index(directory / f"posts-{ids[0]}.json", url)
    posts = json.loads(index.content)
    if not isinstance(posts, list) or {post["id"] for post in posts} != set(ids) or len(posts) != len(ids):
        raise ValueError(f"Incomplete Game-Rave article batch starting at {ids[0]}")
    return index, posts


def game_record(post, checklist_titles, review):
    post_id = str(post["id"])
    source = {"name": "Game-Rave", "url": GAME_RAVE + "?p=" + post_id}
    page = BeautifulSoup(post["content"]["rendered"], "html.parser")
    fields = {}
    for cell in page.find_all(["td", "th"]):
        if (match := FIELD.fullmatch(cell.get_text(" ", strip=True))) and match[2]:
            fields.setdefault(match[1].lower(), match[2])
    title = review.get("title") or game_title(post["title"]["rendered"])
    edition = review.get("edition", title)
    names = list(dict.fromkeys((title, *checklist_titles)))
    publisher, developer = (fields.get(field, "") for field in ("publisher", "developer"))
    codes = review.get("serials", serials(fields.get("sony id", "")))
    release = {
        "key": _key("release", post_id, "US"), "edition": edition, "market": "NA", "channel": "optical-disc",
        "titles": names, "date": fields.get("released", ""), "source": source,
        "developer": developer, "publisher": publisher,
        "creditSources": dict.fromkeys(("developer", "publisher"), source),
        "productCodes": codes,
    }
    for key, field in (("genre", "genre"), ("players", "players"), ("memoryCard", "memory"),
                       ("accessories", "accessories")):
        value = " ".join(fields.get(field, "").split())
        if value and value.casefold() not in {"none", "n/a"}:
            release[key] = value
    if count := re.match(r"\d+", fields.get("cds", "")):
        release["packagedDiscs"] = int(count[0])
    rating = re.split(r"\s+[–-]\s+", fields.get("esrb", ""), maxsplit=1)[0]
    if rating := review.get("rating", RATING_NAMES.get(rating, rating)):
        release["rating"] = rating
    return {
        "key": _key("game", post_id), "title": title, "source": {**source, "record": post_id},
        "aliases": [{"title": name, "regions": ["US"]} for name in names[1:]],
        "developer": developer, "publisher": publisher, "releases": [release],
    }


def retail_list(directory, reviews):
    indexes = [read_index(directory / f"gamerave-{page}.html", GAME_RAVE + f"?page_id={page}")
               for page in CHECKLIST_PAGES]
    titles = _checklist_labels(indexes)
    ids = list(titles)
    games = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index, posts in pool.map(lambda batch: _post_batch(directory, batch),
                                     (ids[i:i + 50] for i in range(0, len(ids), 50))):
            indexes.append(index)
            games.extend(game_record(post, titles[post["id"]], reviews.get(str(post["id"]), {})) for post in posts)
    revision = sha256("".join(index.digest for index in indexes).encode()).hexdigest()
    catalog = {
        "source": {"name": "Game-Rave", "url": CHECKLIST, "revision": revision[:12],
                   "sha256": revision, "rowCount": len(games)},
        "games": sorted(games, key=lambda game: (game["title"].casefold(), game["key"])),
    }
    return catalog, indexes
