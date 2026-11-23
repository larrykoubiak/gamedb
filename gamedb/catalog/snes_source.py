"""Read the pinned SNES retail list as games and market-specific releases."""

from collections import defaultdict
from hashlib import sha256
import re
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from gamedb.catalog.retail_source import cell_text, known_credit, remove_citations, title_and_aliases


REVISION = 1384177751
SOURCE_URL = f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#Retail_releases"
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
MAX_HTML_BYTES = 8 * 1024 * 1024
MARKETS = ("JP", "NA", "PAL")
MARKET_NAMES = ("Japan", "North America", "PAL region")
MARKET_COUNTRIES = {"PAL": {"FR", "GER"}, "NA": {"MX"}, "JP": set()}


def load_html(path=None):
    if path is not None:
        with path.open("rb") as stream:
            html = stream.read(MAX_HTML_BYTES + 1)
    else:
        request = Request(HTML_URL, headers={"User-Agent": "GameDB/2.0 (SNES retail catalog import)"})
        with urlopen(request, timeout=30) as stream:
            html = stream.read(MAX_HTML_BYTES + 1)
    if len(html) > MAX_HTML_BYTES:
        raise ValueError("SNES source exceeds the HTML size limit")
    return html


def _key(*parts):
    return sha256("\x00".join(("gamedb:snes-retail", *parts)).encode()).hexdigest()[:32]


def _market_titles(title, aliases, market):
    regional = [alias["title"] for alias in aliases if market in alias["regions"]]
    local = [alias["title"] for alias in aliases if MARKET_COUNTRIES[market].intersection(alias["regions"])]
    return list(dict.fromkeys((regional or [title]) + local))


def _channel(cell, notes):
    annotations = [notes.get(link.get("href", "").partition("#")[2], "") for link in cell.select("sup.reference a")]
    if any("digital release only" in note and "nintendo power" in note for note in annotations):
        return "nintendo-power"
    if any("sufami turbo" in note for note in annotations):
        return "sufami-turbo"
    return "cartridge"


def parse_retail_list(html, edition_parents, *, release_notes=(), expected_rows=1749):
    soup = BeautifulSoup(html, "html.parser")
    about = soup.html.get("about", "") if soup.html else ""
    revision = re.search(rb'"wgRevisionId"\s*:\s*(\d+)', html)
    if not (about.endswith(f"/revision/{REVISION}") or revision and int(revision[1]) == REVISION):
        raise ValueError(f"Expected Wikipedia revision {REVISION}")
    heading = soup.find(id="Retail_releases")
    table = heading.find_next("table") if heading else None
    if table is None:
        raise ValueError("No SNES retail release table found")
    _, markets, *rows = table.find_all("tr", recursive=False) or table.select("tbody > tr")
    if [cell.get_text(strip=True).partition("[")[0] for cell in markets.find_all("th")] != list(MARKET_NAMES):
        raise ValueError("Unexpected SNES retail table markets")
    if len(rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} SNES retail rows, found {len(rows)}")

    notes = {note["id"]: cell_text(note).casefold() for note in soup.select('li[id^="cite_note-"]')}
    review_notes = {(note["edition"], note["market"]): {"text": note["text"], "url": note["url"]}
                    for note in release_notes}
    games = {}
    for row in rows:
        cells = row.find_all("td", recursive=False)
        # GunForce in this revision omits the trailing reference cell.
        if len(cells) not in (6, 7) or any(cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in cells):
            raise ValueError("Unexpected columns in SNES retail row")
        channel = _channel(cells[0], notes)
        title, aliases = title_and_aliases(cells[0])
        if title in games:
            raise ValueError(f"Duplicate SNES retail source title {title!r}")
        releases = []
        for market, cell in zip(MARKETS, cells[3:6], strict=True):
            remove_citations(cell)
            date = cell_text(cell)
            if date.casefold() in {"unreleased", "cancelled"}:
                continue
            if not re.search(r"\b(?:19|20)\d{2}\b", date):
                raise ValueError(f"Unrecognized {market} release date for {title!r}: {date!r}")
            release = {
                "key": _key("release", title, market), "edition": title, "market": market,
                "titles": _market_titles(title, aliases, market), "date": date,
                "channel": channel if market == "JP" else "cartridge",
            }
            if review := review_notes.pop((title, market), None):
                release["reviewNote"] = review
            releases.append(release)
        if not releases:
            raise ValueError(f"SNES retail row has no published market for {title!r}")
        remove_citations(cells[1])
        remove_citations(cells[2])
        developer, publisher = (cell_text(cell) for cell in cells[1:3])
        games[title] = {
            "key": _key("game", title), "title": title, "aliases": aliases,
            "developer": developer if known_credit(developer) else "",
            "publisher": publisher if known_credit(publisher) else "", "releases": releases,
        }

    for edition, parent in edition_parents.items():
        if edition not in games or parent not in games or parent in edition_parents:
            raise ValueError(f"Invalid SNES edition relationship {edition!r} → {parent!r}")
        games[parent]["releases"].extend(games.pop(edition)["releases"])
    if review_notes:
        raise ValueError(f"SNES review notes refer to unknown releases {list(review_notes)}")

    return {
        "source": {
            "name": "Wikipedia contributors", "url": SOURCE_URL, "revision": REVISION,
            "sha256": sha256(html).hexdigest(), "rowCount": len(rows),
            "license": "https://creativecommons.org/licenses/by-sa/4.0/",
        },
        "games": list(games.values()),
    }
