from gamedb.catalog.pcengine_media import add_manuals
from gamedb.catalog.pcengine_source import REVISION, parse_retail_list


def parse_rows(rows, count):
    html = f"""
        <html about="//en.wikipedia.org/wiki/Special:Redirect/revision/{REVISION}">
        <h2 id="List_of_games">Games</h2>
        <table><tr><th>Title</th></tr>
        <tr><th>Japan</th><th>North America</th></tr>
        {rows}
        </table></html>
    """
    return parse_retail_list(html.encode(), expected_rows=count)


def test_hucard_scope_uses_the_medium_for_each_market():
    catalog = parse_rows("""
        <tr><th>Godzilla</th><td>Hudson Soft</td><td>1993</td><td>1994</td><td>Super CD-ROM²</td></tr>
        <tr><th>1941: Counter Attack</th><td>Hudson Soft</td><td>1991</td><td>Unreleased</td><td>SuperGrafx</td></tr>
        <tr><th>Andre Panza Kick Boxing<br>The Kick Boxing<sup>JP</sup></th><td>NEC (US)<br>Micro World (JP)</td>
            <td>July 31, 1992</td><td>December 1991</td><td>HuCard US Super CD-ROM² JP</td></tr>
        <tr><th>Darius Plus</th><td>NEC Avenue</td><td>1990</td><td>Unreleased</td><td>HuCard (PC-SG)</td></tr>
    """, 4)
    boxing, darius = catalog["games"]
    assert darius["title"] == "Darius Plus"
    assert darius["releases"][0]["medium"] == "SuperGrafx-enhanced HuCard"
    (release,) = boxing["releases"]
    assert (release["market"], release["date"], release["publisher"]) == ("NA", "December 1991", "NEC")
    assert boxing["aliases"] == []


def test_rtype_cards_have_distinct_dates_and_manuals():
    catalog = parse_rows("""
        <tr><th>R-Type</th><td>Hudson Soft</td><td>March 25, 1988 / June 3, 1988</td>
            <td>November 1989</td><td>HuCard</td></tr>
    """, 1)
    (game,) = catalog["games"]
    releases = game["releases"]
    assert [(release["titles"], release["market"], release["date"]) for release in releases] == [
        (["R-Type I"], "JP", "March 25, 1988"), (["R-Type II"], "JP", "June 3, 1988"),
        (["R-Type"], "NA", "November 1989"),
    ]
    assert len({release["key"] for release in releases}) == 3
    manual_urls = [f"https://archive.org/download/example/manual-{page}.pdf" for page in range(1, 4)]
    add_manuals(catalog, {}, {"manuals": [
        {"edition": release["edition"], "market": release["market"], "url": url, "source": "Internet Archive"}
        for release, url in zip(releases, manual_urls, strict=True)
    ]})
    assert [release["manuals"][0]["url"] for release in releases] == manual_urls
