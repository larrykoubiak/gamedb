"""Read the HuCard releases from the pinned PC Engine software list."""

from hashlib import sha256
import re

from bs4 import BeautifulSoup

from gamedb.catalog.retail_source import (
    add_reviewed_releases, cell_text, credit_for_market, regional_credits, remove_citations, title_and_aliases,
)


REVISION = 1386073683
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
SOURCE_URL = f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#List_of_games"
MARKETS = ("JP", "NA")
FORMATS = {
    "HuCard": MARKETS,
    "HuCard (PC-SG)": MARKETS,
    "HuCard US Super CD-ROM² JP": ("NA",),
}
SOURCE = {"name": "Wikipedia contributors", "url": SOURCE_URL}


def _key(*parts):
    return sha256("\x00".join(("gamedb:pcengine-retail", *parts)).encode()).hexdigest()[:32]


def _release(title, market, date, names, *, edition=None):
    edition = edition or title
    return {
        "key": _key("release", title, edition, market), "edition": edition, "market": market,
        "titles": names, "date": date, "channel": "cartridge",
    }


def _distributors(cell):
    for name, markets in regional_credits(cell):
        if region := re.fullmatch(r"(.+?)\s+\((JP|US|NA)\)", name):
            yield region[1], {region[2]}
        else:
            yield name, markets


def _card_releases(title, market, date, names):
    # Japan received two separately packaged halves of the arcade game.
    if title == "R-Type" and market == "JP":
        first, second = date.split(" / ")
        return [_release(title, market, day, [edition], edition=edition)
                for day, edition in ((first, "R-Type I"), (second, "R-Type II"))]
    return [_release(title, market, date, names)]


def parse_retail_list(html, *, additional_releases=(), expected_rows=672):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    heading = soup.find(id="List_of_games")
    table = heading.find_next("table") if heading else None
    if table is None:
        raise ValueError("Missing PC Engine game table")
    _, header, *rows = table.find_all("tr")
    header_cells = header.find_all(["th", "td"], recursive=False)
    for cell in header_cells:
        remove_citations(cell)
    if len(rows) != expected_rows or [cell_text(cell) for cell in header_cells] != ["Japan", "North America"]:
        raise ValueError("Unexpected PC Engine game table layout")

    games = {}
    for row in rows:
        title_cell, publisher_cell, jp, na, format_cell = row.find_all(["th", "td"], recursive=False)
        format_name = cell_text(format_cell)
        if format_name not in FORMATS:
            continue
        title, aliases = title_and_aliases(title_cell)
        aliases = [alias for alias in aliases if set(alias["regions"]) & set(FORMATS[format_name])]
        publishers = list(_distributors(publisher_cell))
        game = {
            "key": _key("game", title), "title": title, "aliases": aliases,
            "developer": "", "publisher": credit_for_market(publishers), "releases": [],
        }
        for market, cell in zip(MARKETS, (jp, na), strict=True):
            if market not in FORMATS[format_name]:
                continue
            remove_citations(cell)
            date = cell_text(cell)
            if date.casefold() == "unreleased":
                continue
            if not re.search(r"\b(?:19|20)\d{2}\b", date):
                raise ValueError(f"Unexpected {market} release date for {title!r}: {date!r}")
            names = [alias["title"] for alias in aliases if market in alias["regions"]]
            for release in _card_releases(title, market, date, names or [title]):
                if name := credit_for_market(publishers, {"US", "NA"} if market == "NA" else {"JP"}):
                    release.update(publisher=name, creditSources={"publisher": SOURCE})
                if format_name == "HuCard (PC-SG)":
                    release["medium"] = "SuperGrafx-enhanced HuCard"
                if title == "Darius Alpha":
                    release["medium"] = "Promotional HuCard"
                game["releases"].append(release)
        if not game["releases"] or title in games:
            raise ValueError(f"Invalid or duplicate PC Engine title {title!r}")
        games[title] = game

    add_reviewed_releases(games, additional_releases, markets=MARKETS,
                          game_key=lambda title: _key("game", title), make_release=_release)
    return {
        "source": {**SOURCE, "revision": REVISION, "sha256": sha256(html).hexdigest(),
                   "rowCount": len(rows), "license": "https://creativecommons.org/licenses/by-sa/4.0/"},
        "games": sorted(games.values(), key=lambda game: game["title"].casefold()),
    }
