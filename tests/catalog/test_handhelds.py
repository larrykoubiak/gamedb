from gamedb.catalog.handheld_artwork import fill_handheld_artwork
from gamedb.catalog.handheld_media import _dat_games, _dsi_ware, _playdate_games
from gamedb.catalog.handhelds import HandheldCatalog, apply_handheld_retail_review
from gamedb.catalog.references import SourceIndex
from gamedb.catalog.retail import retail_tables
from gamedb.explorer.related_media import _read_translation_index


def test_published_3ds_tables_have_valid_postgres_identifiers():
    assert retail_tables("3ds") == (
        "app.threeds_retail_catalog", "app.threeds_retail_image", "app.threeds_retail_soundtrack",
    )


def test_dat_release_has_artwork_evidence_without_a_local_download():
    source = SourceIndex("https://example.org/handheld.dat", b'''
clrmamepro (
    version "2026.11.14"
)
game (
    name "Example (Europe, USA) (Rev 1)"
    region "Europe / USA"
    serial "CTR-P-BEEE"
    rom ( name "Example.3ds" sha1 1234567890123456789012345678901234567890 )
)
game (
    name "Example (USA) (Prototype)"
    region "USA"
    serial "CTR-P-DEMO"
)
''')
    builder = HandheldCatalog("3ds", {})
    _dat_games(builder, source, "cartridge")
    game, = builder.payload()["games"]
    assert game["title"] == "Example"
    assert {release["market"] for release in game["releases"]} == {"NA", "PAL"}
    for release in game["releases"]:
        assert release["status"] == "unmatched"
        assert "archives" not in release
        assert release["productCodes"] == ["CTR-P-BEEE"]
        assert release["artworkArchives"][0]["archiveNames"] == ["Example (Europe, USA) (Rev 1).zip"]


def test_dsi_store_title_joins_by_product_code():
    builder = HandheldCatalog("dsi", {})
    builder.add(
        ["Example"], ["Japan"], {"name": "No-Intro", "url": "https://datomatic.no-intro.org/"},
        channel="dsiware", codes=["KEPJ"],
    )
    source = SourceIndex("https://www.nintendo.co.jp/ds/dsiware/software/01.html", '''
<a class="softResultItem__body" href="../../../ds/dsiware/kepj/index.html">
  <div class="softResultItem__img"><img src="./img/thumb/KEPJ.png"></div>
  <span class="softinfo__title">サンプル</span>
  <span class="softinfo__date">2009.4.1 配信開始</span>
</a>
'''.encode())
    _dsi_ware(builder, source)
    game, = builder.payload()["games"]
    release, = game["releases"]
    assert release["titles"] == ["Example", "サンプル"]
    assert release["date"] == "2009-04-01"
    assert release["artwork"]["title"]["url"].endswith("/img/thumb/KEPJ.png")


def test_handheld_art_requires_a_unique_title_and_compatible_market(tmp_path):
    builder = HandheldCatalog("gb", {})
    source = {"name": "Test", "url": "https://example.org"}
    builder.add(["A Game", "Shared Name"], ["Europe", "USA"], source, channel="cartridge")
    builder.add(["Other Game", "Shared Name"], ["USA"], source, channel="cartridge")
    catalog = builder.payload()
    thumbnails = tmp_path / "Nintendo - Game Boy" / "Named_Boxarts"
    thumbnails.mkdir(parents=True)
    for name in ("A Game (USA) (En,Fr).png", "Shared Name (USA).png"):
        (thumbnails / name).touch()
    first = fill_handheld_artwork(catalog, "gb", tmp_path, {})
    game, other = catalog["games"]
    north_america, europe = game["releases"]
    assert north_america["market"] == "NA"
    assert north_america["artwork"]["boxart"]["regions"] == ["USA"]
    assert "artwork" not in europe and "artwork" not in other["releases"][0]
    assert first["after"]["illustrated"] == 1
    second = fill_handheld_artwork(catalog, "gb", tmp_path, {})
    assert second["before"] == second["after"]


def test_reviewed_mame_bootleg_is_removed_without_dropping_a_licensed_compilation():
    builder = HandheldCatalog("gb", {})
    for name, record in (("4 in 1", "4in1_001"), ("4-in-1 Fun Pak", "funpak")):
        builder.add([name], ["USA"], {"name": "MAME", "url": "https://example.org", "record": record},
                    channel="cartridge")
    catalog = builder.payload()
    review = {"retailReview": {"mameRecords": ["4in1_001"]}}
    result = apply_handheld_retail_review(catalog, review)
    assert result == {"excludedTitles": 1, "excludedReleases": 1, "mergedTitles": 0}
    assert [game["title"] for game in catalog["games"]] == ["4-in-1 Fun Pak"]
    assert catalog["summary"]["byMarket"]["NA"]["unmatched"] == 1
    assert not apply_handheld_retail_review(catalog, review)


def test_playdate_store_excludes_catalog_promotion_cards():
    source = SourceIndex("https://play.date/games/search/", b'''
<li class="gameCard" id="game1">
  <h2 class="gameTitle"><a href="/games/season-one/">24 unique games</a></h2>
</li>
<li class="gameCard" id="game83">
  <div class="gameCardImage" style="background-image: url('https://play.date/media/games/83/cover.png')"></div>
  <h2 class="gameTitle"><a href="/games/game/">Example</a></h2>
  <h3 class="gameDeveloper">by Studio</h3>
  <h3 class="gamePublishDate">01/14/2025</h3>
</li>
''')
    builder = HandheldCatalog("playdate", {})
    _playdate_games(builder, source)
    game, = builder.payload()["games"]
    release, = game["releases"]
    assert game["title"] == "Example"
    assert release["date"] == "2025-01-14"
    assert release["artwork"]["boxart"]["url"].endswith("/cover.png")
import json



def test_explorer_indexes_ds_xdelta_patches(tmp_path):
    patch = {"key": "a" * 64, "sha256": "b" * 64, "layout": "nds", "format": "xdelta",
             "size": 1024, "signatures": ["c" * 32]}
    path = tmp_path / ".gamedb-translations.json"
    path.write_text(json.dumps({"version": 1, "translations": [patch]}), encoding="utf-8")
    records, by_signature = _read_translation_index(path, 1)
    assert records[patch["key"]] == patch
    assert by_signature[patch["signatures"][0]] == [patch]
