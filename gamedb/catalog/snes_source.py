"""Read the pinned SNES retail list as games and market-specific releases."""

from collections import defaultdict
from hashlib import sha256
import re
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


REVISION = 1384177751
SOURCE_URL = f"https://en.wikipedia.org/wiki/Special:PermanentLink/{REVISION}#Retail_releases"
HTML_URL = f"https://en.wikipedia.org/w/rest.php/v1/revision/{REVISION}/html"
MAX_HTML_BYTES = 8 * 1024 * 1024
MARKETS = ("JP", "NA", "PAL")
MARKET_NAMES = ("Japan", "North America", "PAL region")
MARKET_COUNTRIES = {"PAL": {"FR", "GER"}, "NA": {"MX"}, "JP": set()}
UNKNOWN_CREDITS = {"", "-", "—", "unknown", "unknown developer", "unknown publisher", "n/a"}


def known_credit(value):
    return bool(value and "?" not in value and value.strip().casefold() not in UNKNOWN_CREDITS)


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


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split())


def _remove_citations(cell):
    for note in cell.find_all("sup", class_="reference"):
        note.decompose()


def _title_and_aliases(cell):
    _remove_citations(cell)
    for helper in cell.select('.noprint, .sortkey, [style*="display:none"], [style*="display: none"]'):
        helper.decompose()
    # One language link in this revision uses a separate Bracket template
    # instead of the usual interlanguage-link markup.
    for link in cell.select('a[rel="mw:WikiLink/Interwiki"]'):
        group = link.parent
        before, after = group.previous_sibling, group.next_sibling
        if (group.get("about") and re.fullmatch(r"[a-z-]{2,12}", _text(link))
                and getattr(before, "name", None) == getattr(after, "name", None) == "span"
                and before.get("about") == after.get("about") == group["about"]
                and _text(before) == "[" and _text(after) == "]"):
            before.decompose()
            after.decompose()
            group.decompose()
    # The retail table puts market abbreviations in superscripts at the end
    # of each alternate title. Preserve them as data, apart from citations.
    for marker in cell.find_all("sup"):
        marker.replace_with("\x1f" + _text(marker))
    for line_break in cell.find_all("br"):
        line_break.replace_with("\x1e")
    primary, *alternates = re.split(r"[\x1e•]", cell.get_text())
    title = " ".join(primary.split())
    if not title or "\x1f" in primary:
        raise ValueError("SNES retail row has an invalid primary title")
    aliases = []
    for alternate in alternates:
        name, _, marker = alternate.partition("\x1f")
        name = " ".join(name.split())
        if name:
            aliases.append({"title": name, "regions": re.findall(r"[A-Z]+", marker)})
    return title, aliases


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

    notes = {note["id"]: _text(note).casefold() for note in soup.select('li[id^="cite_note-"]')}
    review_notes = {(note["edition"], note["market"]): {"text": note["text"], "url": note["url"]}
                    for note in release_notes}
    games = {}
    for row in rows:
        cells = row.find_all("td", recursive=False)
        # GunForce in this revision omits the trailing reference cell.
        if len(cells) not in (6, 7) or any(cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in cells):
            raise ValueError("Unexpected columns in SNES retail row")
        channel = _channel(cells[0], notes)
        title, aliases = _title_and_aliases(cells[0])
        if title in games:
            raise ValueError(f"Duplicate SNES retail source title {title!r}")
        releases = []
        for market, cell in zip(MARKETS, cells[3:6], strict=True):
            _remove_citations(cell)
            date = _text(cell)
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
        _remove_citations(cells[1])
        _remove_citations(cells[2])
        developer, publisher = (_text(cell) for cell in cells[1:3])
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
