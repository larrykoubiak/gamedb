"""Read the original Sega Saturn release list from a pinned revision."""

from hashlib import sha256
import re

from bs4 import BeautifulSoup

from .retail_source import (
    add_reviewed_releases, cell_text, credit_for_market, regional_credits, remove_citations, title_and_aliases,
)


REVISION = 1382248864
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
SOURCE = {"name": "Wikipedia contributors",
          "url": f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#Games"}
TABLE_MARKETS = ("NA", "PAL", "JP")
MARKETS = (*TABLE_MARKETS, "BR", "KR", "AS")
TERRITORIES = {
    "NA": {"NA", "US"}, "PAL": {"PAL", "EU", "EUR", "AU", "AUS", "FRA", "GER"},
    "JP": {"J", "JP", "JPN"}, "BR": {"BR", "BRA"}, "KR": {"KR", "KOR"}, "AS": {"AS", "TW", "ASIA"},
}


def _key(*parts):
    return sha256("\0".join(("gamedb:saturn-retail", *parts)).encode()).hexdigest()[:32]


def _release(title, market, date, names, *, edition=None):
    edition = edition or title
    return {"key": _key("release", title, edition, market), "edition": edition, "market": market,
            "titles": names, "date": date, "channel": "optical-disc"}


def _game(row):
    title_cell, developer_cell, publisher_cell, *dates = row.find_all(["th", "td"], recursive=False)
    for label in title_cell.find_all(["br", "sup"]):
        if label.name == "br":
            break
        label.decompose()
    title, aliases = title_and_aliases(title_cell)
    aliases = [{"title": alias["title"], "regions": [market for market, regions in TERRITORIES.items()
                                                    if regions.intersection(alias["regions"])]}
               for alias in aliases]
    developers, publishers = map(regional_credits, (developer_cell, publisher_cell))
    game = {"key": _key("game", title), "title": title, "aliases": aliases,
            "developer": credit_for_market(developers), "publisher": credit_for_market(publishers), "releases": []}
    for market, date_cell in zip(TABLE_MARKETS, dates, strict=True):
        remove_citations(date_cell)
        date = cell_text(date_cell)
        if date.casefold() == "unreleased":
            continue
        if not re.search(r"\b(?:19|20)[0-9?]{2}(?!\w)", date) and date not in {"Unknown", "?", "Released"}:
            raise ValueError(f"Unexpected {market} release date for {title!r}: {date!r}")
        names = [alias["title"] for alias in aliases if market in alias["regions"]] or [title]
        release = _release(title, market, date, list(dict.fromkeys(names)))
        credits = {field: credit for field, values in (("developer", developers), ("publisher", publishers))
                   if (credit := credit_for_market(values, TERRITORIES[market]))}
        release.update(credits, creditSources=dict.fromkeys(credits, SOURCE))
        game["releases"].append(release)
    return game


def _table_rows(soup, heading_id):
    heading = soup.find(id=heading_id)
    table = heading.find_next("table", class_="wikitable") if heading else None
    if table is None:
        raise ValueError(f"Missing Sega Saturn table {heading_id}")
    header, *rows = table.find_all("tr")
    cells = header.find_all("th")[-len(TABLE_MARKETS):]
    for cell in cells:
        remove_citations(cell)
    if tuple(cell_text(cell) for cell in cells) != TABLE_MARKETS:
        raise ValueError(f"Unexpected Sega Saturn release columns in {heading_id}")
    return rows


def parse_retail_list(html, *, compilations=(), additional_releases=(), excluded=(), omitted_releases=None,
                      expected_rows=1028):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    rows = _table_rows(soup, "Games")
    if len(rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} Sega Saturn retail game rows")
    games = {}
    for row in rows:
        game = _game(row)
        if game["title"] in games or not game["releases"]:
            raise ValueError(f"Invalid or duplicate Saturn title {game['title']!r}")
        games[game["title"]] = game
    for title in excluded:
        if title not in games:
            raise ValueError(f"Unknown excluded Sega Saturn title {title}")
        del games[title]
    for title, review in (omitted_releases or {}).items():
        game = games[title]
        original = game["releases"]
        game["releases"] = [release for release in original if release["market"] not in review["markets"]]
        if not game["releases"] or len(original) - len(game["releases"]) != len(review["markets"]):
            raise ValueError(f"Invalid Sega Saturn release omission for {title}")
    if compilations:
        supplemental = {}
        for row in _table_rows(soup, "Non-game_software_and_compilations"):
            game = _game(row)
            if game["title"] in compilations:
                supplemental[game["title"]] = game
        if set(supplemental) != set(compilations) or games.keys() & supplemental.keys():
            raise ValueError("Unknown or duplicate Sega Saturn compilation")
        games.update(supplemental)
    add_reviewed_releases(games, additional_releases, markets=MARKETS,
                          game_key=lambda title: _key("game", title), make_release=_release)
    return {"source": {**SOURCE, "revision": REVISION, "sha256": sha256(html).hexdigest(), "rowCount": len(rows),
                       "license": "https://creativecommons.org/licenses/by-sa/4.0/"},
            "games": sorted(games.values(), key=lambda game: game["title"].casefold())}
