from gamedb.catalog.n64_rom import N64_LAYOUTS, Z64_MAGIC, rom_byte_order
from gamedb.catalog.n64_source import REVISION, parse_retail_list
from gamedb.catalog.patching import apply_translation


def test_nintendo64_distinguishes_the_two_bomberman_64_cartridges():
    html = f"""
        <html about="//en.wikipedia.org/wiki/Special:Redirect/revision/{REVISION}">
        <h2 id="Games">Games</h2>
        <table class="sticky-header-multi">
        <tr><th>Title</th></tr><tr><th>Japan</th><th>North America</th><th>PAL</th></tr>
        <tr><th><a href="./Bomberman_64_(1997_video_game)">Bomberman 64</a><sup>NA</sup>
            <br>Baku Bomberman<sup>JP</sup></th><td>Hudson</td><td>Hudson</td><td>Action</td>
            <td>1997</td><td>1997</td><td>1997</td></tr>
        <tr><th><a href="./Bomberman_64_(2001_video_game)">Bomberman 64</a></th>
            <td>Racjin</td><td>Hudson</td><td>Action</td><td>2001</td><td>Unreleased</td><td>Unreleased</td></tr>
        </table></html>
    """
    original, later = parse_retail_list(html.encode(), expected_rows=2)["games"]
    assert (original["title"], original["releases"][0]["titles"]) == ("Bomberman 64", ["Baku Bomberman"])
    assert (later["title"], later["releases"][0]["titles"]) == ("Bomberman 64 (2001)", ["Bomberman 64"])
    assert original["key"] != later["key"]


def test_nintendo64_patch_uses_the_expected_byte_order_and_returns_z64():
    base = Z64_MAGIC + bytes(range(64))
    for layout in N64_LAYOUTS:
        ordered = rom_byte_order(base, layout)
        expected = rom_byte_order(ordered[:64] + b"abcd", "z64")
        patch = b"PATCH\x00\x00\x40\x00\x04abcdEOF"
        assert apply_translation(base, patch, "ips", layout) == expected
