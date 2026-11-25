from bs4 import BeautifulSoup

from gamedb.catalog.mastersystem_media import sms_power_matches
from gamedb.catalog.mastersystem_source import MARKETS, _read_table, add_brazilian_releases


def test_card_and_pack_in_keep_their_release_scope():
    html = BeautifulSoup("""
        <h2 id="Games">Games</h2>
        <table><tr><th>Games</th></tr>
        <tr><th>JP</th><th>NA</th><th>PAL</th><th>BR</th></tr>
        <tr><th>Hang-On</th><td>Sega</td><td>Sega</td>
            <td>1985<sup class="reference"><a href="#cite_note-segacard-50">[a]</a></sup></td>
            <td>1986</td><td>1987</td><td></td></tr>
        </table>
    """, "html.parser")
    (game,) = _read_table(html, "Games", MARKETS, 1)
    jp, na, pal = game["releases"]
    assert jp["medium"] == "My Card Mark III"
    assert na["includedIn"]["title"] == "Hang-On & Safari Hunt"
    assert na["channel"] == "pack-in"
    assert pal["channel"] == "cartridge"


def test_brazilian_release_requires_a_unique_source_title():
    game = {"key": "sonic", "title": "Sonic the Hedgehog", "aliases": [], "releases": []}
    catalog = {"games": [game]}
    html = b"""
        <table><tr><td>SMS</td><td><a href="/Games/SonicTheHedgehog-SMS">Sonic the Hedgehog</a></td>
        <td><img alt="Brazil"></td><td><img alt="Platform"></td></tr></table>
    """
    match = sms_power_matches(catalog, html, {})
    assert add_brazilian_releases(catalog, match) == 1
    (release,) = game["releases"]
    assert (release["market"], release["date"]) == ("BR", "")
    assert release["source"]["url"].endswith("/Games/SonicTheHedgehog-SMS")

    other = {"key": "other", "title": game["title"], "aliases": [], "releases": []}
    assert not sms_power_matches({"games": [game, other]}, html, {})
