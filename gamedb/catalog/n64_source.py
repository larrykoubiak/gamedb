"""Read Nintendo 64 cartridge editions from a pinned release list."""

from hashlib import sha256
import re

from bs4 import BeautifulSoup

from gamedb.catalog.retail_source import (
    add_reviewed_releases, cell_text, credit_for_market, regional_credits, remove_citations, title_and_aliases,
)


REVISION = 1386089812
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
SOURCE_URL = f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#Games"
SOURCE = {"name": "Wikipedia contributors", "url": SOURCE_URL}
TABLE_MARKETS = ("JP", "NA", "PAL")
MARKETS = (*TABLE_MARKETS, "BR")
COUNTRY_ALIASES = {"FRA": "PAL", "AUS": "PAL"}


def _key(*parts):
    return sha256("\x00".join(("gamedb:n64-retail", *parts)).encode()).hexdigest()[:32]


def _release(title, market, date, names, *, edition=None):
    edition = edition or title
    return {
        "key": _key("release", title, edition, market), "edition": edition, "market": market,
        "titles": names, "date": date, "channel": "cartridge",
    }


def _titles(cell):
    link = cell.find("a", href=True)
    # The list annotates some main titles as well as their alternate names.
    for label in cell.find_all(["br", "sup"]):
        if label.name == "br":
            break
        label.decompose()
    title, aliases = title_and_aliases(cell)
    name = "Bomberman 64 (2001)" if link and link["href"] == "./Bomberman_64_(2001_video_game)" else title
    return name, title, aliases


def parse_retail_list(html, *, additional_releases=(), regional_corrections=None, expected_rows=388):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    heading = soup.find(id="Games")
    table = heading.find_next("table", class_="sticky-header-multi") if heading else None
    if table is None:
        raise ValueError("Missing Nintendo 64 game table")
    _, header, *rows = table.find_all("tr")
    cells = header.find_all("th")
    for cell in cells:
        remove_citations(cell)
    if len(rows) != expected_rows or [cell_text(cell) for cell in cells] != ["Japan", "North America", "PAL"]:
        raise ValueError("Unexpected Nintendo 64 game table layout")

    games = {}
    regional_corrections = regional_corrections or {}
    for row in rows:
        title_cell, developer_cell, publisher_cell, _, *dates = row.find_all(["th", "td"], recursive=False)
        title, primary, aliases = _titles(title_cell)
        developers, publishers = map(regional_credits, (developer_cell, publisher_cell))
        reviewed = regional_corrections.get(title, {})
        reviewed_names = {market: record["titles"] for market, record in reviewed.items() if record.get("titles")}
        aliases = [{**alias, "regions": [region for region in alias["regions"]
                                       if COUNTRY_ALIASES.get(region, region) not in reviewed_names]}
                   for alias in aliases]
        aliases = [alias for alias in aliases if alias["regions"]]
        aliases.extend({"title": name, "regions": [market]} for market, names in reviewed_names.items()
                       for name in names if name != title)
        game = {
            "key": _key("game", title), "title": title,
            "aliases": [{"title": alias["title"], "regions": list(dict.fromkeys(
                COUNTRY_ALIASES.get(region, region) for region in alias["regions"]
            ))} for alias in aliases],
            "developer": credit_for_market(developers), "publisher": credit_for_market(publishers), "releases": [],
        }
        for market, date_cell in zip(TABLE_MARKETS, dates, strict=True):
            remove_citations(date_cell)
            date = cell_text(date_cell)
            if date.casefold() == "unreleased":
                continue
            if not re.search(r"\b(?:19|20)\d{2}\b", date):
                raise ValueError(f"Unexpected {market} release date for {title!r}: {date!r}")
            names = [alias["title"] for alias in aliases if market in alias["regions"]]
            country_titles = [alias["title"] for alias in aliases
                              if any(COUNTRY_ALIASES.get(region) == market for region in alias["regions"])]
            correction = reviewed.get(market, {})
            release = _release(title, market, correction.get("date", date), reviewed_names.get(market) or list(
                dict.fromkeys([*(names or [primary]), *country_titles])
            ))
            if "date" in correction:
                release["dateSource"] = correction["source"]
            if "titles" in correction:
                release["source"] = correction["source"]
            territories = {"JP": {"JP"}, "NA": {"NA", "US"}, "PAL": {"PAL", "EU", "AUS", "FRA"}}[market]
            credits = {key: name for key, values in (("developer", developers), ("publisher", publishers))
                       if (name := credit_for_market(values, territories))}
            if credits:
                release.update(credits, creditSources=dict.fromkeys(credits, SOURCE))
            game["releases"].append(release)
        if not game["releases"] or title in games:
            raise ValueError(f"Invalid or duplicate Nintendo 64 title {title!r}")
        games[title] = game

    add_reviewed_releases(games, additional_releases, markets=MARKETS,
                          game_key=lambda title: _key("game", title), make_release=_release)
    return {
        "source": {**SOURCE, "revision": REVISION, "sha256": sha256(html).hexdigest(), "rowCount": len(rows),
                   "license": "https://creativecommons.org/licenses/by-sa/4.0/"},
        "games": sorted(games.values(), key=lambda game: game["title"].casefold()),
    }
