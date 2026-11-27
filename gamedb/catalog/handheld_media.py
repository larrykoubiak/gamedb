"""Release lists and media evidence specific to the handheld catalogs."""

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from gamedb.vgm.inventory import BROWSER_AUDIO, JOSHW_TRACKS
from gamedb.vgm.joshw import EDITION, HANDHELD_BUCKETS, INDEX_URL, superseded_sources, soundtrack_name, title_revision
from gamedb.vgm.matching import spelling_key

from .handhelds import COUNTRIES, DEVELOPMENT, NO_INTRO, SUFFIX, TOSEC, _date, _names, _strip_regions, _territories
from .retail import _compact_title
from .retail_media import _manual_key
from .soundtracks import add_soundtrack_sources


THUMBNAILS = {
    "lynx": ("Atari - Lynx", "1f80ecfa4bf824af5be14af736e61c8f41fd21f5"),
    "wonderswan": ("Bandai - WonderSwan", "a40e1aacbeffc00a5306e1a88c3a56b2e8006947"),
    "wonderswancolor": ("Bandai - WonderSwan Color", "5aa7ef325716f2f958458cec5ce3f3376153455d"),
    "leapster": ("LeapFrog - Leapster Learning Game System", "7bf338386514f849b9584f0fceb324ba22537eb3"),
    "gb": ("Nintendo - Game Boy", "f033af49af2d9761d6821aff479bb0ba5feea5e3"),
    "gbc": ("Nintendo - Game Boy Color", "0931985ba8a3a9f38fb87f006611a13dc094260f"),
    "gba": ("Nintendo - Game Boy Advance", "23b8665408e767fd3220bfb83fd5ad8dfe1a9aa1"),
    "nds": ("Nintendo - Nintendo DS", "a119dcab8fa04c9974b9c229eda824318d923322"),
    "dsi": ("Nintendo - Nintendo DSi", "982c27d6d54eb3d884042f90d5748820730b4637"),
    "3ds": ("Nintendo - Nintendo 3DS", "a1e242aca9d194ba7c168e38e14c637ff206189f"),
    "pokemini": ("Nintendo - Pokemon Mini", "4185f3cb95440af9ea1623ecd20c59d3683603ac"),
    "gamegear": ("Sega - Game Gear", "ac963d8297e70c4f06fb9a1cf378c321f8769a64"),
    "ngp": ("SNK - Neo Geo Pocket", "3932af2130b55ae1d666632c79fc99515ed5438c"),
    "ngpc": ("SNK - Neo Geo Pocket Color", "1ce701a6ca52d4258e67c5db75e9ca42f566fa11"),
    "psp": ("Sony - PlayStation Portable", "caa8a7f67f63ebaa470135edaa19366fd05731e8"),
    "psvita": ("Sony - PlayStation Vita", "52b54659dc84be4e122c96bca5ebc1f17f57c683"),
    "gamecom": ("Tiger - Game.com", "4c261a00ddc7feab810814a93b65e9f84269fc9f"),
    "supervision": ("Watara - Supervision", "1a385b7009be1c117417f6c54a9dd7e5b17de3c4"),
}
LIBRETRO_REVISION = "f89f09cbe13f9f7863ecf20d0ebf2c5ce53be029"
LIBRETRO_DATS = f"https://raw.githubusercontent.com/libretro/libretro-database/{LIBRETRO_REVISION}/metadat/no-intro/"
PSP_DAT = LIBRETRO_DATS.replace("/no-intro/", "/redump/") + "Sony%20-%20PlayStation%20Portable.dat"
DAT_LISTS = {
    "3ds": (("3ds.dat", "Nintendo - Nintendo 3DS", "cartridge"),
            ("new3ds.dat", "Nintendo - New Nintendo 3DS", "cartridge"),
            ("3ds-digital.dat", "Nintendo - Nintendo 3DS (Digital)", "eshop"),
            ("new3ds-digital.dat", "Nintendo - New Nintendo 3DS (Digital)", "eshop")),
    "dsi": (("dsi.dat", "Nintendo - Nintendo DSi", "dsiware"),),
    "psvita": (("psvita.dat", "Sony - PlayStation Vita", "unknown"),),
}
PLAYDATE = "https://play.date/games/"
DSI_WARE = "https://www.nintendo.co.jp/ds/dsiware/software/"
MANUAL_PAGES = {
    "gb": (("kirkland-gb.html", "https://www.videogamemanual.com/gameboy/index.html", "Kirkland's Manual Labor", "NA"),),
    "gbc": (("kirkland-gbc.html", "https://www.videogamemanual.com/gbc/index.html", "Kirkland's Manual Labor", "NA"),),
    "gba": (("kirkland-gba.html", "https://www.videogamemanual.com/gba/index.html", "Kirkland's Manual Labor", "NA"),
            ("nintendo-gba-us.html", "https://en-americas-support.nintendo.com/app/answers/detail/a_id/16961/p/50/c/693",
             "Nintendo", "NA")),
    "nds": (("nintendo-ds-us.html", "https://en-americas-support.nintendo.com/app/answers/detail/a_id/16905/", "Nintendo", "NA"),
            ("nintendo-ds-eu.html", "https://www.nintendo.com/en-za/Support/Legacy-system/Nintendo-DS-games-manuals-1006833.html",
             "Nintendo", "PAL")),
    "3ds": (("nintendo-3ds-us.html", "https://en-americas-support.nintendo.com/app/answers/detail/a_id/16903/", "Nintendo", "NA"),
            ("nintendo-3ds-eu.html", "https://www.nintendo.com/en-gb/Support/Legacy-system/Nintendo-3DS-games-electronic-manuals-850636.html",
             "Nintendo", "PAL"),
            ("nintendo-3ds-au.html", "https://www.nintendo.com/au/support/articles/nintendo-3ds-software-manuals/",
             "Nintendo", "PAL")),
}
TOSEC_MANUALS = {
    "lynx": ("Atari/Lynx", "NA"), "gamate": ("Bit Corporation/Gamate", "UNK"),
    "gba": ("Nintendo/Game Boy Advance", "NA"), "ngage": ("Nokia/N-Gage", "PAL"), "gamegear": ("Sega/Game Gear", "NA"),
    "psp": ("Sony/PlayStation Portable", None),
}
PSP_MANUALS = ("SonyPSPManuals", "SonyPSPManualsv1.2", "PSP-instruction-manuals-and-document-dat")
DS_MANUALS = "NintendoDSManuals"
VITA_MANUALS = "persona-4-golden"
DS_MANUAL_NAME = re.compile(
    r"(.+?)(usa|europe|australia|japan|germany|france|spain|italy|netherlands)"
    r"(?:(?:en|ja|fr|de|es|it|nl|pt|sv|no|da|fi|pl|ko|zh|ru)){0,12}(?:ndsienhanced)?[ab]?$", re.I,
)
TRACK_FORMATS = {suffix[1:] for suffix in BROWSER_AUDIO | JOSHW_TRACKS} | {"gbs", "vgm", "vgz", "sgc", "aac"}
MEDIA_TAG = re.compile(r"(?:^\[|\()(?:bios|firmware|dlc|update|theme|avatar|unlock key|soundtrack|video|"
                       r"virtual console|bonus|demo|kiosk|prototype|sample|tool|system software|unl)\b", re.I)
DAT_FIELDS = re.compile(r'^\s*(name|region|serial) "((?:[^"\\]|\\.)*)"\s*$', re.M)
MIRRORABLE = {"www.videogamemanual.com", "www.nintendo.com", "assets.nintendo.eu", "csassets.nintendo.com",
              "www.nintendo.co.jp", "en-americas-support.nintendo.com", "archive.org", "www.digitpress.com"}
LANGUAGES = {"english": "English", "français": "French", "español": "Spanish"}


def read_handheld_sources(platform, directory, indexes, warnings, read):
    sources = {name: url for name, url, *_ in MANUAL_PAGES.get(platform, ())}
    for filename, name, _ in DAT_LISTS.get(platform, ()):
        sources[filename] = LIBRETRO_DATS + quote(name) + ".dat"
    if platform == "psp":
        sources["psp.dat"] = PSP_DAT
        sources.update({f"{item}.json": f"https://archive.org/metadata/{item}" for item in PSP_MANUALS})
    if platform == "nds":
        sources[f"{DS_MANUALS}.json"] = f"https://archive.org/metadata/{DS_MANUALS}"
    if platform == "psvita":
        sources[f"{VITA_MANUALS}.json"] = f"https://archive.org/metadata/{VITA_MANUALS}"
    if platform == "dsi":
        sources.update({f"nintendo-dsi-{page:02}.html": f"{DSI_WARE}{page:02}.html" for page in range(1, 11)})
    if platform == "playdate":
        sources.update({"playdate-season-one.html": "https://static-cdn.play.date/games/season-one/",
                        "playdate-season-two.html": f"{PLAYDATE}seasons/two/",
                        "playdate-season-three.html": f"{PLAYDATE}seasons/three/"})
    if platform in HANDHELD_BUCKETS:
        sources["joshw.json"] = INDEX_URL
    for name, url in sources.items():
        read(directory, name, url, indexes, warnings)
    if platform == "playdate":
        page = 1
        while index := read(directory, f"playdate-catalog-{page}.html", f"{PLAYDATE}search/?q=&page={page}&sort=name",
                            indexes, warnings):
            next_page = BeautifulSoup(index.content, "html.parser").select_one(".pagerNavigatorButton.next a[href]")
            if next_page is None or parse_qs(urlsplit(next_page["href"]).query).get("page") != [str(page + 1)]:
                break
            page += 1


def _dat_games(builder, index, channel):
    content = index.content.decode("utf-8-sig")
    version = re.search(r'^\s*version "([^"]+)"', content, re.M)
    provider = "Redump" if channel == "optical-disc" else "No-Intro"
    url = "http://redump.org/discs/system/psp/" if provider == "Redump" else NO_INTRO
    source = {"name": provider, "url": url, "revision": version[1] if version else LIBRETRO_REVISION,
              "index": index.url, "sha256": index.digest}
    for entry in re.split(r"^game\s*\(\s*$", content, flags=re.M)[1:]:
        fields = dict(DAT_FIELDS.findall(entry))
        name = fields.get("name", "")
        if (not name or DEVELOPMENT.search(name) or MEDIA_TAG.search(name)
                or re.search(r" - Update [\dv]|^(?:sampler disc|game demo)\b", name, re.I)):
            continue
        title = name
        while (suffix := SUFFIX.search(title)) and not _strip_regions(title)[1]:
            title = title[:suffix.start()]
        title, regions = _strip_regions(title)
        regions = regions or _territories(fields.get("region", ""))
        if not title or not any(region in COUNTRIES for region in regions):
            continue
        if builder.platform == "dsi" and re.search(r"DSi (?:Shop|Camera|Menu|Sound|System)|System Settings|Demo Video", title, re.I):
            continue
        names = _names(title)
        game = builder.find(names)
        game = builder.add(names, regions, source, channel=channel, game=game, codes=_territories(fields.get("serial", "")))
        scope = {COUNTRIES[region] for region in regions if region in COUNTRIES}
        for release in game["releases"].values():
            if release["channel"] == channel and release["market"] in scope:
                # This filename identifies artwork in Libretro, independently of local download eligibility.
                evidence = {"title": name, "archiveNames": [name + ".zip"], "regions": regions, "versions": [], "revisions": []}
                release.setdefault("artworkArchives", []).append(evidence)


def _dsi_ware(builder, index):
    source = {"name": "Nintendo", "url": index.url, "sha256": index.digest}
    for row in BeautifulSoup(index.content, "html.parser").select(".softResultItem__body"):
        title = row.select_one(".softinfo__title")
        date = row.select_one(".softinfo__date")
        publisher = row.select_one(".softinfo__maker")
        if not title or not date:
            continue
        name = title.get_text(" ", strip=True)
        when = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", date.get_text())
        if not name or not when or re.fullmatch(r"ニンテンドーDSi(?:カメラ|サウンド|ショップ)", name):
            continue
        image = row.select_one(".softResultItem__img img[src]")
        image_url = urljoin(index.url, image["src"]) if image else None
        artwork = None
        if image_url and re.fullmatch(r"https://www\.nintendo\.co\.jp/ds/dsiware/software/img/thumb/[A-Z0-9]+\.png", image_url):
            artwork = {"title": {"url": image_url, "source": source, "regions": ["JP"], "basis": "publisher-artwork"}}
        code = Path(urlsplit(row.get("href", "")).path).parent.name.upper()
        owners = builder.codes["JP", code]
        game = builder.games[next(iter(owners))] if len(owners) == 1 else builder.find([name], market="JP")
        builder.add([name], ["JP"], source, game=game, channel="dsiware",
                    publisher=publisher.get_text(strip=True) if publisher else "",
                    date=f"{when[1]}-{int(when[2]):02}-{int(when[3]):02}", artwork=artwork)


def _playdate_games(builder, index):
    soup = BeautifulSoup(index.content, "html.parser")
    for row in soup.select(".gameCard[id]"):
        if not re.fullmatch(r"game\d+", row["id"]):
            continue
        link = row.select_one(".gameTitle a[href]")
        developer = row.select_one(".gameDeveloper")
        if not link or developer is None or not re.fullmatch(r"/games/[^/]+/", link["href"]):
            continue
        header = link.get_text(" ", strip=True)
        if not header:
            continue
        url = urljoin("https://play.date/", link["href"])
        source = {"name": "Panic", "url": url, "index": index.url, "sha256": index.digest}
        image = row.select_one(".gameCardImage[style]")
        image_url = re.search(r"url\(['\"]?(https://(?:static-cdn\.)?play\.date/media/games/[^\s'\";)]+)", image["style"]) if image else None
        artwork = {"boxart": {"url": image_url[1], "source": source, "basis": "publisher-artwork", "regions": ["WORLD"]}} if image_url else None
        date = row.select_one(".gamePublishDate")
        date_match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", date.get_text(strip=True)) if date else None
        builder.add([header], ["World"], source, game=builder.find([header]), channel="download", artwork=artwork,
                    developer=developer.get_text(" ", strip=True).removeprefix("by "),
                    date=f"{date_match[3]}-{date_match[1]}-{date_match[2]}" if date_match else "")


def add_handheld_sources(builder, indexes, reference):
    for filename, _, channel in DAT_LISTS.get(builder.platform, ()):
        if index := indexes.get(filename):
            _dat_games(builder, index, channel)
    if index := indexes.get("psp.dat"):
        _dat_games(builder, index, "optical-disc")
    for name, index in indexes.items():
        if name.startswith("nintendo-dsi-"):
            _dsi_ware(builder, index)
        if builder.platform == "playdate" and name.startswith("playdate"):
            _playdate_games(builder, index)
    for item in reference.get("releases", ()):
        names = [item["title"], *item.get("aliases", ())]
        builder.add(names, item.get("regions", ()), item["source"], channel=item["channel"], game=builder.find(names),
                    date=_date(item.get("date")), publisher=item.get("publisher", ""), artwork=item.get("artwork"),
                    developer=item.get("developer", ""), codes=item.get("productCodes", ()))


def _pdf_links(index, source, market):
    site = urlsplit(index.url)
    soup = BeautifulSoup(index.content, "html.parser")
    for link in soup.select("a[href]"):
        href = urlsplit(urljoin(index.url, link["href"]))
        if href.hostname not in MIRRORABLE or href.scheme not in {"http", "https"}:
            continue
        if source.startswith("Kirkland"):
            label = link.get_text(" ", strip=True)
            title, regions = _strip_regions(label)
            if href.hostname != site.hostname or not href.path.startswith(site.path.rsplit("/", 1)[0] + "/"):
                continue
            if not href.path.casefold().endswith(".pdf") or "USA" not in regions:
                continue
            language = "English"
        else:
            if href.hostname == "www.nintendo.com" and href.path.startswith("/consumer/"):
                continue  # The old directory now redirects to Nintendo's storefront.
            if not href.path.casefold().endswith(".pdf") and not (href.hostname == "csassets.nintendo.com" and "manual" in href.path.lower()):
                continue
            label = link.get_text(" ", strip=True)
            language = LANGUAGES.get(label.casefold(), "English")
            if market == "NA":
                if not re.search(r"/gameslist/manuals/|/software/|(?:dsiware|3ds|nds|ds|agb)[_-]", href.path, re.I):
                    continue
                row = link.find_parent("tr")
                cell = row.find("td") if row else None
                if cell is None:
                    continue
                title = cell.get_text(" ", strip=True)
                regions = ["US"]
            elif site.path.startswith("/au/"):
                group = link.find_parent("ul")
                heading = group.find_previous_sibling("p") if group else None
                if heading is None or label not in {"Electronic Manual", "Quick Start Guide"}:
                    continue
                title = heading.get_text(" ", strip=True).removeprefix("Nintendo Selects").strip()
                regions = ["AU"]
            else:
                title = re.sub(r"\s*-\s*(?:Electronic )?Manual\s*\(PDF[^()]*\)\s*$", "", label, flags=re.I)
                if title == label:
                    continue
                regions = ["EU"]
        title = re.sub(r"[™®]", "", title).strip()
        if not title:
            continue
        manual_url = href._replace(scheme="https", path=quote(unquote(href.path), safe="/!$&'()*+,;=:@"), fragment="").geturl()
        yield title, market, {"name": title + " — manual", "regions": regions,
                              "language": language, "format": "PDF", "source": source, "sourceUrl": index.url, "url": manual_url}


def _tosec_manuals(platform):
    if platform not in TOSEC_MANUALS:
        return
    directory, default_market = TOSEC_MANUALS[platform]
    root = Path(os.environ.get("GAMEDB_ROM_ROOT") or "/mnt/synology") / "roms/TOSEC-PIX"
    for path in sorted((root / directory / "Manuals/Games").glob("*.zip")):
        match = re.fullmatch(r"(.+?) \((?:19|20)[\dx]{2}(?:-\d{2}){0,2}\)\([^)]*\)(.*)", path.stem)
        if not match:
            continue
        title, labels = match.groups()
        regions = [region for region in re.findall(r"\(([^)]+)\)", labels) if region in COUNTRIES]
        markets = {COUNTRIES[region] for region in regions}
        relative = path.relative_to(root).as_posix()
        for market in markets or ({default_market} if default_market else set()):
            yield title, market, {"name": title + " — manual", "regions": regions, "format": "PDF", "source": "TOSEC PIX",
                                  "url": f"{TOSEC}#pix/{quote(relative)}", "sourceUrl": TOSEC, "localArchive": relative}


def _archived_pdfs(index, item):
    payload = json.loads(index.content)
    if payload.get("metadata", {}).get("identifier") != item:
        raise ValueError(f"Unexpected manual archive {item}")
    for doc in payload["files"]:
        filename = doc["name"]
        if (doc.get("source") != "original" or doc.get("private") in {"true", True}
                or not filename.lower().endswith(".pdf") or not doc.get("sha1") or not str(doc.get("size", "")).isdigit()):
            continue
        yield PurePosixPath(filename).stem, {
            "format": "PDF", "source": "Internet Archive", "sourceUrl": f"https://archive.org/details/{item}",
            "url": f"https://archive.org/download/{item}/{quote(filename)}", "sha1": doc["sha1"], "size": int(doc["size"]),
        }


def _psp_manuals(index, item):
    for stem, manual in _archived_pdfs(index, item):
        title, regions = _strip_regions(stem)
        serial = re.search(r"\s+([A-Z]{4})(\d{5})$", stem)
        if serial:
            title = stem[:serial.start()]
            prefix = serial[1]
            if prefix in {"ULUS", "UCUS", "NPUG", "NPUH", "NPUZ"}:
                regions = ["USA"]
            elif prefix.startswith("NPE") or prefix in {"ULES", "UCES"}:
                regions = ["Europe"]
            elif prefix.startswith("NPJ") or prefix in {"ULJM", "ULJS", "UCJS"}:
                regions = ["Japan"]
        if not regions:
            continue
        manual.update(name=_names(title)[0] + " — manual", regions=regions)
        for market in {COUNTRIES[region] for region in regions}:
            if serial:
                yield f"{serial[1]}-{serial[2]}", market, manual
            yield title, market, manual


def add_handheld_manuals(platform, catalog, indexes, reference):
    by_title, by_compact = defaultdict(dict), defaultdict(dict)
    for game in catalog["games"]:
        for release in game["releases"]:
            archive_titles = [name for archive in release.get("archives", ()) for name in _names(archive["title"])]
            for title in (game["title"], *release["titles"], *archive_titles, *release.get("productCodes", ())):
                by_title[_manual_key(title)][game["key"]] = game
                if platform == "nds":
                    by_compact[_compact_title(title)][game["key"]] = game
    candidates = list(_tosec_manuals(platform))
    for filename, _, source, market in MANUAL_PAGES.get(platform, ()):
        if index := indexes.get(filename):
            candidates.extend(_pdf_links(index, source, market))
    if platform == "psp":
        for item in PSP_MANUALS:
            if index := indexes.get(f"{item}.json"):
                candidates.extend(_psp_manuals(index, item))
    if platform == "nds" and (index := indexes.get(f"{DS_MANUALS}.json")):
        for stem, manual in _archived_pdfs(index, DS_MANUALS):
            match = DS_MANUAL_NAME.fullmatch(stem)
            if not match:
                continue
            games = by_compact[_compact_title(match[1])]
            if len(games) == 1:
                game, = games.values()
                country = match[2].upper() if match[2].casefold() == "usa" else match[2].title()
                manual.update(name=game["title"] + " — manual", regions=[country])
                candidates.append((game["title"], COUNTRIES[country], manual))
    if platform == "psvita" and (index := indexes.get(f"{VITA_MANUALS}.json")):
        for stem, manual in _archived_pdfs(index, VITA_MANUALS):
            title, regions = _strip_regions(stem)
            manual.update(name=title + " — manual", regions=regions)
            for market in {COUNTRIES[region] for region in regions} or {"UNK"}:
                candidates.append((title, market, manual))
    for item in reference.get("manuals", ()):
        candidates.append((item["title"], item["market"], {key: value for key, value in item.items() if key not in {"title", "market"}}))
    aliases = reference.get("manualAliases", {})
    unavailable = set(reference.get("unavailableManuals", ()))
    for title, market, manual in candidates:
        if manual["url"] in unavailable:
            continue
        matches = by_title[_manual_key(aliases.get(title, title))]
        if len(matches) != 1:
            continue
        game, = matches.values()
        releases = [release for release in game["releases"] if release["market"] == market]
        if not releases:
            releases = [release for release in game["releases"] if release["market"] in {"WORLD", "UNK"}]
        if not releases and market == "UNK":
            releases = [release for release in game["releases"]
                        if _manual_key(title) in {_manual_key(name) for name in release["titles"]}]
        for release in releases:
            manuals = release.setdefault("manuals", [])
            if not any(item["url"] == manual["url"] for item in manuals):
                manuals.append(manual)


def add_handheld_soundtracks(platform, catalog, indexes):
    bucket = HANDHELD_BUCKETS.get(platform)
    index = indexes.get("joshw.json")
    if not bucket or not index:
        return 0
    by_title = defaultdict(dict)
    for game in catalog["games"]:
        for title in {game["title"], *(name for release in game["releases"] for name in release["titles"])}:
            by_title[spelling_key(title)][game["key"]] = game
    entries = [row for row in json.loads(index.content)
               if row["sd"] == bucket and row["nm"].endswith(".7z") and not row.get("old")]
    replaced = superseded_sources(row["nm"] for row in entries)
    sources, seen = [], set()
    for row in entries:
        path = PurePosixPath(row["nm"])
        if (row["nm"] in replaced or DEVELOPMENT.search(path.stem) or EDITION.search(path.stem)
                or path.is_absolute() or ".." in path.parts):
            continue
        title, aliases = soundtrack_name(bucket, path)
        title, _ = title_revision(title)
        if not title or DEVELOPMENT.search(title) or EDITION.search(title):
            continue
        matches = {key: game for name in (title, *aliases) for key, game in by_title[spelling_key(name)].items()}
        if len(matches) != 1:
            continue
        game, = matches.values()
        fingerprint = game["key"], path.stem.casefold()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        sources.append({"game": game["title"], "gameKey": game["key"], "title": title,
                        "url": f"https://{bucket}.joshw.info/{quote(path.as_posix())}",
                        "markets": sorted({release["market"] for release in game["releases"]}),
                        "size": row["sz"], "revision": int(datetime.fromisoformat(row["md"]).replace(tzinfo=timezone.utc).timestamp())})
    add_soundtrack_sources(catalog, platform, sources)
    return sum(len(game.get("soundtrackSources", ())) for game in catalog["games"])
