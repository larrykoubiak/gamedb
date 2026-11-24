"""Read shared retail list markup and apply reviewed release additions."""

import re


UNKNOWN_CREDITS = {"", "-", "—", "unknown", "unknown developer", "unknown publisher", "n/a"}


def known_credit(value):
    return bool(value and "?" not in value and value.strip().casefold() not in UNKNOWN_CREDITS)


def cell_text(node):
    return " ".join(node.get_text(" ", strip=True).split())


def remove_citations(cell):
    for note in cell.find_all("sup", class_="reference"):
        note.decompose()


def regional_credits(cell):
    remove_citations(cell)
    for marker in cell.find_all("sup"):
        marker.replace_with("\x1f" + cell_text(marker))
    for line_break in cell.find_all("br"):
        line_break.replace_with("\x1e")
    credits = []
    for line in cell.get_text().split("\x1e"):
        name, _, scope = line.partition("\x1f")
        name = " ".join(name.split())
        if known_credit(name):
            credits.append((name, set(re.findall(r"[A-Z]+", scope))))
    return credits


def credit_for_market(credits, regions=()):
    scope = set(regions)
    local = [name for name, codes in credits if codes & scope]
    general = [name for name, codes in credits if not codes or "WW" in codes]
    return " / ".join(dict.fromkeys(local or general))


def add_reviewed_releases(games, additions, *, markets, game_key, make_release):
    edition_markets = {(release["edition"], release["market"]) for game in games.values()
                       for release in game["releases"]}
    for review in additions:
        title, market = review["game"], review["market"]
        edition = review.get("edition", title)
        new_game = title not in games
        if (new_game != review.get("newGame", False) or market not in markets
                or (edition, market) in edition_markets):
            raise ValueError(f"Invalid reviewed retail release {title!r} / {edition!r} ({market})")

        credits = {field: review[field] for field in ("developer", "publisher") if review.get(field)}
        if new_game:
            games[title] = {"key": game_key(title), "title": title, "aliases": [], "releases": [],
                            "developer": credits.get("developer", ""), "publisher": credits.get("publisher", "")}
        game = games[title]
        local_title = review.get("title", edition)
        source = review["source"]
        release = make_release(title, market, review.get("date", ""), [local_title], edition=edition)
        release.update(credits, source=source)
        if date_source := review.get("dateSource"):
            release["dateSource"] = date_source
        if credits:
            release["creditSources"] = dict.fromkeys(credits, source)
        game["releases"].append(release)
        edition_markets.add((edition, market))

        alias = {"title": local_title, "regions": [market]}
        if local_title != title and alias not in game["aliases"]:
            game["aliases"].append(alias)


def title_and_aliases(cell):
    remove_citations(cell)
    for helper in cell.select('.noprint, .sortkey, [style*="display:none"], [style*="display: none"]'):
        helper.decompose()
    # Some language links use separate Bracket templates around the link.
    for link in cell.select('a[rel="mw:WikiLink/Interwiki"]'):
        group = link.parent
        before, after = group.previous_sibling, group.next_sibling
        if (group.get("about") and re.fullmatch(r"[a-z-]{2,12}", cell_text(link))
                and getattr(before, "name", None) == getattr(after, "name", None) == "span"
                and before.get("about") == after.get("about") == group["about"]
                and cell_text(before) == "[" and cell_text(after) == "]"):
            before.decompose()
            after.decompose()
            group.decompose()
    # Save superscript market abbreviations with each alternate title.
    for marker in cell.find_all("sup"):
        marker.replace_with("\x1f" + cell_text(marker))
    for line_break in cell.find_all("br"):
        line_break.replace_with("\x1e")
    primary, *alternates = re.split(r"[\x1e•]", cell.get_text())
    title = " ".join(primary.split())
    if not title or "\x1f" in primary:
        raise ValueError("Retail row has an invalid primary title")
    aliases = []
    for alternate in alternates:
        name, _, marker = alternate.partition("\x1f")
        name = " ".join(name.split())
        if name:
            aliases.append({"title": name, "regions": re.findall(r"[A-Z]+", marker)})
    return title, aliases
