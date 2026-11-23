"""Read the pinned regional NES and Famicom cartridge release tables."""

from collections import Counter
from hashlib import sha256
import re

from bs4 import BeautifulSoup

from gamedb.catalog.retail_source import (
    cell_text, credit_for_market, regional_credits, remove_citations, title_and_aliases,
)


REVISION = 1385181858
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
SOURCE_URL = f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#Licensed_games"
CREDIT_SOURCE = {"name": "Wikipedia contributors", "url": SOURCE_URL}
INDEPENDENT_SOURCE = {**CREDIT_SOURCE, "url": SOURCE_URL.replace("#Licensed_games", "#Unlicensed_games")}
MARKETS = ("JP", "NA", "PAL")
MARKET_CODES = {
    "JP": {"JP"}, "NA": {"NA", "US", "CA", "MX"},
    "PAL": {"PAL", "EU", "AUS", "AU", "FR", "GER", "DE", "ESP", "ES", "ITA", "IT", "UK", "GB"},
}
DATE = re.compile(r"\b(?:19|20)\d{2}\b")


def _key(*parts):
    return sha256("\x00".join(("gamedb:nes-retail", *parts)).encode()).hexdigest()[:32]


def _rows(soup, heading, *, markets, expected, summary=False):
    section = soup.find(id=heading)
    table = section.find_next("table") if section else None
    if table is not None and summary:
        table = table.find_next("table")
    if table is None:
        raise ValueError(f"Missing NES source section {heading!r}")
    rows = [cells for row in table.find_all("tr") if (cells := row.find_all("td", recursive=False))]
    expected_columns = 4 if markets == ("JP",) else 7
    if len(rows) != expected or any(len(cells) != expected_columns for cells in rows):
        raise ValueError(f"Unexpected NES source layout for {heading!r}")
    for cells in rows:
        title, aliases = title_and_aliases(cells[0])
        developers, publishers = map(regional_credits, cells[1:3])
        releases = {}
        for market, cell in zip(markets, cells[-len(markets):], strict=True):
            remove_citations(cell)
            date = cell_text(cell)
            if date.casefold().startswith("unreleased"):
                continue
            if not DATE.search(date):
                raise ValueError(f"Unexpected {market} date for {title!r}: {date!r}")
            releases[market] = date
        if not releases:
            raise ValueError(f"NES source title {title!r} has no release date")
        yield title, aliases, developers, publishers, releases


def _market_titles(title, aliases, market):
    local = [alias["title"] for alias in aliases if market in alias["regions"]]
    variants = [alias["title"] for alias in aliases if MARKET_CODES[market].intersection(alias["regions"])]
    return list(dict.fromkeys((local or [title]) + variants))


def _add_independent_releases(games, archives):
    reviewed = {}
    for archive in archives:
        if not archive.get("independentRetail"):
            continue
        title, edition, market = (archive[field] for field in ("title", "edition", "market"))
        publisher, date = archive["publisher"], archive["date"]
        if edition in games or market not in MARKETS or not publisher or not DATE.fullmatch(date):
            raise ValueError(f"Invalid independent NES release {edition!r}")
        releases = reviewed.setdefault(edition, {})
        release = {
            "key": _key("release", edition, market), "edition": edition, "market": market,
            "titles": [edition], "date": date, "channel": "cartridge", "publisher": publisher,
            "creditSources": {"publisher": INDEPENDENT_SOURCE},
        }
        if releases.setdefault(market, release) != release:
            raise ValueError(f"Conflicting independent NES release {title!r}")
    for edition, releases in reviewed.items():
        values = list(releases.values())
        games[edition] = {
            "key": _key("game", edition), "title": edition, "aliases": [], "developer": "",
            "publisher": " / ".join(dict.fromkeys(release["publisher"] for release in values)), "releases": values,
        }


def parse_retail_list(html, *, counts=(1370, 7, 7), reviewed_archives=()):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    rows = [*_rows(soup, "Licensed_games", markets=MARKETS, expected=counts[0], summary=True),
            *_rows(soup, "Compilations", markets=MARKETS, expected=counts[1])]
    datach = list(_rows(soup, "Bandai_Datach_games", markets=("JP",), expected=counts[2]))
    uses = Counter(title for title, *_ in rows)
    games = {}
    for is_datach, row in [(False, row) for row in rows] + [(True, row) for row in datach]:
        title, aliases, developers, publishers, dates = row
        developer, publisher = map(credit_for_market, (developers, publishers))
        edition = title
        if is_datach:
            edition = f"{title} (Datach)"
        elif uses[title] > 1:
            edition = f"{title} ({publisher or developer})"
        if edition in games:
            raise ValueError(f"Duplicate NES edition {edition!r}")
        releases = []
        for market, date in dates.items():
            credits = {field: value for field, choices in (("developer", developers), ("publisher", publishers))
                       if (value := credit_for_market(choices, MARKET_CODES[market]))}
            titles = [f"Datach - {title}"] if is_datach else _market_titles(title, aliases, market)
            releases.append({
                "key": _key("release", edition, market), "edition": edition, "market": market,
                "titles": titles, "date": date, "channel": "cartridge",
                **credits, "creditSources": dict.fromkeys(credits, CREDIT_SOURCE),
            })
        if edition != title:
            aliases = [{"title": title, "regions": []}, *aliases]
        games[edition] = {"key": _key("game", edition), "title": edition, "aliases": aliases,
                          "developer": developer, "publisher": publisher, "releases": releases}
    _add_independent_releases(games, reviewed_archives)
    return {
        "source": {**CREDIT_SOURCE, "revision": REVISION, "sha256": sha256(html).hexdigest(), "rowCount": len(rows) + len(datach),
                   "license": "https://creativecommons.org/licenses/by-sa/4.0/"},
        "games": sorted(games.values(), key=lambda game: game["title"].casefold()),
    }
