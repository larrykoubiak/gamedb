"""Read the pinned Mega Drive cartridge release list."""

from hashlib import sha256
import re

from bs4 import BeautifulSoup

from gamedb.catalog.retail_source import (
    add_reviewed_releases, cell_text, credit_for_market, regional_credits, remove_citations, title_and_aliases,
)


REVISION = 1386009379
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
SOURCE_URL = f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#Licensed_games"
MARKETS = ("JP", "NA", "PAL", "BR", "KR", "AS")
LOCAL_MARKERS = {"PAL": {"AUS", "ESP", "EU", "FR", "GER"}}
CREDIT_SOURCE = {"name": "Wikipedia contributors", "url": SOURCE_URL}
DATE = re.compile(r"\b(?:19|20)\d{2}\b")
NETWORK_ONLY = re.compile(r"exclusively released via the Sega (?:Channel|Meganet)", re.I)


def _key(*parts):
    return sha256("\x00".join(("gamedb:megadrive-retail", *parts)).encode()).hexdigest()[:32]


def _release(title, market, date, names, *, edition=None, credits=None):
    edition = edition or title
    return {
        "key": _key("release", title, edition, market), "edition": edition, "market": market,
        "titles": names, "date": date, "channel": "cartridge", **(credits or {}),
    }


def _market_names(title, aliases, market):
    regional = [alias["title"] for alias in aliases if market in alias["regions"]]
    local = [alias["title"] for alias in aliases
             if LOCAL_MARKERS.get(market, set()).intersection(alias["regions"])]
    return list(dict.fromkeys([*(regional or [title]), *local]))


def _credit_for(credits, market):
    return credit_for_market(credits, {market, *LOCAL_MARKERS.get(market, ())})


def _release_dates(cells, notes, title):
    dates = {}
    for market, cell in zip(MARKETS[:4], cells, strict=True):
        if any(NETWORK_ONLY.search(notes.get(link.get("href", "").partition("#")[2], ""))
               for link in cell.select("sup.reference a")):
            continue
        remove_citations(cell)
        if market == "BR" and cell_text(cell):
            markers = cell.find_all("sup")
            if len(markers) != 1 or cell_text(markers[0]) not in {"BR", "KR"}:
                raise ValueError(f"Unexpected other market for {title!r}")
            market = cell_text(markers[0])
            markers[0].decompose()
        date = cell_text(cell)
        if not date or date.casefold() == "unreleased":
            continue
        if not DATE.search(date):
            raise ValueError(f"Unexpected {market} release date for {title!r}: {date!r}")
        dates[market] = date
    return dates


def _compilations(soup, reviews, games):
    heading = soup.find(id="Compilations")
    table = heading.find_next("table") if heading else None
    if table is None:
        raise ValueError("Missing Mega Drive compilations table")
    rows = {}
    for row in table.find_all("tr")[1:]:
        title, developer, publisher, _ = row.find_all(["th", "td"], recursive=False)
        rows[cell_text(title)] = (credit_for_market(regional_credits(developer)),
                                 credit_for_market(regional_credits(publisher)))
    for source_title, review in reviews.items():
        developer, publisher = rows[source_title]
        title = review.get("title", source_title)
        releases = [_release(title, market, entry["date"], [entry.get("title", title)])
                    for market, entry in review["markets"].items()]
        if title in games:
            raise ValueError(f"Compilation duplicates Mega Drive game {title!r}")
        games[title] = {
            "key": _key("game", title), "title": title, "developer": developer, "publisher": publisher,
            "aliases": [{"title": release["titles"][0], "regions": [release["market"]]}
                        for release in releases if release["titles"][0] != title],
            "releases": releases,
        }


def parse_retail_list(html, compilations=None, *, additional_releases=(), expected_rows=878):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    heading = soup.find(id="Licensed_games")
    table = heading.find_next("table") if heading else None
    if table is None:
        raise ValueError("Missing licensed Mega Drive release table")
    _, markets, *rows = table.find_all("tr")
    if len(rows) != expected_rows or [t.get_text(strip=True).partition("[")[0] for t in
                                      markets.find_all("th")] != ["JP", "NA", "PAL", "Other"]:
        raise ValueError("Unexpected licensed Mega Drive table layout")

    notes = {note["id"]: cell_text(note) for note in soup.select('li[id^="cite_note-"]')}
    games, skipped = {}, []
    previous = None
    for row in rows:
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 7 and cells[0].name == "th":
            title, aliases = title_and_aliases(cells.pop(0))
            multiple = row.th.get("rowspan") == "2"
            previous = (title, aliases) if multiple else None
        elif len(cells) == 6 and previous:
            title, aliases = previous
            multiple, previous = True, None
        else:
            raise ValueError("Unexpected Mega Drive release row")
        developers, publishers = map(regional_credits, cells[:2])
        developer, publisher = _credit_for(developers, None), _credit_for(publishers, None)
        dates = _release_dates(cells[2:], notes, title)
        if not dates:
            skipped.append(title)
            continue
        if title in games and not multiple:
            raise ValueError(f"Duplicate Mega Drive title {title!r}")
        game = games.setdefault(title, {
            "key": _key("game", title), "title": title, "aliases": aliases,
            "developer": "" if multiple else developer, "publisher": "" if multiple else publisher, "releases": [],
        })
        edition = f"{title} ({developer})" if multiple else title
        for market, date in dates.items():
            credits = {field: value for field, names in (("developer", developers), ("publisher", publishers))
                       if (value := _credit_for(names, market))}
            if credits:
                credits["creditSources"] = {field: CREDIT_SOURCE for field in credits}
            game["releases"].append(_release(
                title, market, date, _market_names(title, aliases, market),
                edition=edition, credits=credits,
            ))
    if compilations:
        _compilations(soup, compilations, games)

    add_reviewed_releases(games, additional_releases, markets=MARKETS,
                          game_key=lambda title: _key("game", title), make_release=_release)
    return {
        "source": {
            "name": "Wikipedia contributors", "url": SOURCE_URL, "revision": REVISION,
            "sha256": sha256(html).hexdigest(), "rowCount": len(rows),
            "license": "https://creativecommons.org/licenses/by-sa/4.0/",
        },
        "networkOnlyTitles": skipped,
        "games": sorted(games.values(), key=lambda game: game["title"].casefold()),
    }
