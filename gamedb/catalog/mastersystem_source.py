"""Read the pinned Master System and Mark III release tables."""

from hashlib import sha256
import re

from bs4 import BeautifulSoup

from gamedb.catalog.retail_source import (
    add_reviewed_releases, cell_text, credit_for_market, regional_credits, remove_citations, title_and_aliases,
)


REVISION = 1383992196
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
SOURCE_URL = f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}"
MARKETS = ("JP", "NA", "PAL", "BR")
CREDIT_SOURCE = {"name": "Wikipedia contributors", "url": SOURCE_URL}
DATE = re.compile(r"\b(?:19|20)\d{2}\b")

# These releases were distributed as part of the listed compilation.
PACK_INS = {
    ("Astro Warrior", "PAL"): "Astro Warrior / Pit Pot",
    ("Hang-On", "NA"): "Hang-On & Safari Hunt",
    ("Marksman Shooting & Trap Shooting", "PAL"): "Marksman Shooting / Trap Shooting / Safari Hunt",
    ("Pit Pot", "PAL"): "Astro Warrior / Pit Pot",
    ("Safari Hunt", "NA"): "Hang-On & Safari Hunt",
    ("Safari Hunt", "PAL"): "Marksman Shooting / Trap Shooting / Safari Hunt",
}
REGIONAL_TITLES = {
    ("Wonder Boy in Monster Land", "BR"): "Mônica no Castelo do Dragão",
    ("Wonder Boy III: The Dragon's Trap", "BR"): "Turma da Mônica em o Resgate",
}


def _key(*parts):
    return sha256("\x00".join(("gamedb:mastersystem-retail", *parts)).encode()).hexdigest()[:32]


def _release(title, market, date, names, *, edition=None):
    edition = edition or title
    return {
        "key": _key("release", title, edition, market), "edition": edition,
        "market": market, "titles": names, "date": date, "channel": "cartridge",
    }


def _release_medium(cell, title, market):
    notes = {anchor.get("href", "").partition("#")[2] for anchor in cell.select("sup.reference a")}
    if title == "Snail Maze":
        return "Built-in game"
    if (title, market) in PACK_INS:
        return "Pack-in compilation"
    if "cite_note-87" in notes:
        return "Magazine prize"
    if notes & {"cite_note-cardandcart-31", "cite_note-90"}:
        return "Sega Card and cartridge"
    if "cite_note-segacard-50" in notes:
        return "My Card Mark III" if market == "JP" else "Sega Card"
    return None


def _read_table(soup, section, markets, count):
    heading = soup.find(id=section)
    table = heading.find_next("table") if heading else None
    if table is None:
        raise ValueError(f"Missing Master System {section} table")
    _, header, *rows = table.find_all("tr")
    for cell in header.find_all("th"):
        remove_citations(cell)
    if len(rows) != count or tuple(cell_text(cell) for cell in header.find_all("th")) != markets:
        raise ValueError(f"Unexpected Master System {section} table layout")

    for row in rows:
        title_cell, developer_cell, publisher_cell, *cells = row.find_all(["th", "td"], recursive=False)
        title, aliases = title_and_aliases(title_cell)
        developers, publishers = map(regional_credits, (developer_cell, publisher_cell))
        game = {
            "key": _key("game", title), "title": title, "aliases": aliases,
            "developer": credit_for_market(developers), "publisher": credit_for_market(publishers),
            "releases": [],
        }
        compilation = section == "Compilations"
        if compilation:
            cells.pop()
        for market, cell in zip(markets, cells, strict=True):
            medium = _release_medium(cell, title, market)
            remove_citations(cell)
            date = cell_text(cell)
            if not date or date.casefold() == "unreleased":
                continue
            if not DATE.search(date):
                raise ValueError(f"Unexpected Master System {market} date for {title!r}: {date!r}")
            names = [alias["title"] for alias in aliases if market in alias["regions"]]
            if regional := REGIONAL_TITLES.get((title, market)):
                names = [regional]
                aliases.append({"title": regional, "regions": [market]})
            release = _release(title, market, date, names or [title])
            if medium:
                release["medium"] = medium
            if title == "Snail Maze":
                release["channel"] = "built-in"
            if bundle := PACK_INS.get((title, market)):
                release.update(channel="pack-in", includedIn={"key": _key("game", bundle), "title": bundle})
            if compilation:
                release["source"] = {**CREDIT_SOURCE, "url": SOURCE_URL + "#Compilations"}
            credits = {
                key: name for key, names in (("developer", developers), ("publisher", publishers))
                if (name := credit_for_market(names, {market}))
            }
            if credits:
                release.update(credits, creditSources=dict.fromkeys(credits, CREDIT_SOURCE))
            game["releases"].append(release)
        if not game["releases"]:
            raise ValueError(f"No Master System release for {title!r}")
        yield game


def parse_retail_list(html, *, additional_releases=()):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    games = {}
    for game in (*_read_table(soup, "Games", MARKETS, 314),
                 *_read_table(soup, "Compilations", MARKETS[1:], 9)):
        title = game["title"]
        if title in games:
            raise ValueError(f"Duplicate Master System title {title!r}")
        games[title] = game
    add_reviewed_releases(games, additional_releases, markets=MARKETS,
                          game_key=lambda title: _key("game", title), make_release=_release)
    return {
        "source": {
            "name": "Wikipedia contributors", "url": SOURCE_URL + "#Games", "revision": REVISION,
            "sha256": sha256(html).hexdigest(), "rowCount": 314, "compilationRows": 9,
            "license": "https://creativecommons.org/licenses/by-sa/4.0/",
        },
        "games": sorted(games.values(), key=lambda game: game["title"].casefold()),
    }


def add_brazilian_releases(catalog, matched_games):
    """Add documented Brazilian editions when the pinned list gives no release."""
    additional = []
    games = {game["title"]: game for game in catalog["games"]}
    for title, game in games.items():
        if not (record := matched_games.get(game["key"])) or "Brazil" not in record["regions"]:
            continue
        if any(release["market"] == "BR" for release in game["releases"]):
            continue
        additional.append({
            "game": title, "market": "BR", "source": {"name": "SMS Power!", "url": record["url"]},
        })
    add_reviewed_releases(games, additional, markets=MARKETS,
                          game_key=lambda title: _key("game", title), make_release=_release)
    return len(additional)
