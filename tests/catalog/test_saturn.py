from gamedb.catalog.saturn import merge_packaging_editions
from gamedb.catalog.saturn_discs import complete_sets
from gamedb.catalog.saturn_source import REVISION, parse_retail_list


def test_release_dates_follow_the_saturn_table_order():
    html = f"""<html about="/revision/{REVISION}"><body>
      <h2 id="Games">Games</h2><table class="wikitable">
        <tr><th>Title</th><th>Developer</th><th>Publisher</th><th>NA</th><th>PAL</th><th>JP</th></tr>
        <tr><td>Game</td><td>Studio</td><td>Publisher</td>
          <td>Unreleased</td><td>July 3, 1998</td><td>May 1, 1997</td></tr>
      </table></body></html>"""
    game, = parse_retail_list(html.encode(), expected_rows=1)["games"]
    assert [(release["market"], release["date"]) for release in game["releases"]] == [
        ("PAL", "July 3, 1998"), ("JP", "May 1, 1997"),
    ]


def test_zero_based_saturn_discs_require_the_full_numbered_set():
    archives, headers = [], {}
    for index in (2, 0, 1):
        name = f"Game (Japan) (Disc {index}).zip"
        archives.append({"title": "Game", "regions": ["JP"], "signature": f"{index:032x}",
                         "archiveNames": [name], "discs": [{"name": name}]})
        headers[name] = {"serial": "T-0000G", "number": index + 1, "count": 3}
    assert list(complete_sets(archives[:2], headers)) == []
    bundle, = complete_sets(archives, headers)
    assert bundle["archiveNames"] == [f"Game (Japan) (Disc {index}).zip" for index in range(3)]
    assert [disc["number"] for disc in bundle["discs"]] == [1, 2, 3]
    assert [part["signature"] for part in bundle["components"]] == [f"{index:032x}" for index in range(3)]


def test_packaging_edition_links_only_reviewed_pressings_and_keeps_its_cover():
    original = {
        "key": "original-release", "edition": "Game", "market": "JP", "status": "matched",
        "archives": [{"signature": signature, "discs": [{}]} for signature in ("first", "second", "other")],
        "productCodes": ["T-1000G"], "artwork": {"boxart": "jewel case", "snap": "gameplay"},
        "manuals": [{"name": "Game", "url": "manual.pdf"}],
    }
    variant = {"key": "edition-release", "edition": "Game: Special Edition", "market": "JP",
               "status": "unmatched", "artwork": {"boxart": "outer box"}}
    game = {"key": "original-game", "title": "Game", "releases": [original],
            "soundtrackLinks": [{"key": "soundtrack", "releases": [original["key"]]}]}
    catalog = {"games": [game, {"key": "edition-game", "title": variant["edition"], "releases": [variant]}]}
    merge_packaging_editions(catalog, [{
        "game": "Game", "edition": variant["edition"], "market": "JP",
        "signatures": ["first", "second"], "productCodes": ["T-1001G"],
        "sharedManual": True, "evidence": "Verified in both packages",
    }])
    assert catalog["games"] == [game]
    assert game["formerKeys"] == ["edition-game"]
    assert game["releases"] == [original, variant]
    assert variant["status"] == "matched"
    assert variant["productCodes"] == ["T-1001G"]
    assert [archive["signature"] for archive in variant["archives"]] == ["first", "second"]
    assert variant["artwork"] == {"boxart": "outer box", "snap": "gameplay"}
    assert variant["manuals"][0]["url"] == original["manuals"][0]["url"]
    assert game["soundtrackLinks"][0]["releases"] == [original["key"], variant["key"]]
