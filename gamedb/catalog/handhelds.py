"""Build handheld retail snapshots from scoped release and preservation evidence."""

from collections import Counter, defaultdict
from hashlib import sha256
import json
import re
from xml.etree import ElementTree

from sqlalchemy import text

from gamedb.config import PROJECT_ROOT, ProjectEnvironment
from gamedb.database import create_database_engine
from gamedb.launchbox.matching import title_key
from gamedb.vgm.joshw import HANDHELD_BUCKETS

from . import retail
from .cartridges import COUNTRY_MARKETS
from .disc_variants import add_disc_variants
from .genres import genre_values, read_genre_aliases
from .references import MAME_RAW, read_index
from .retail_media import LAUNCHBOX_GAMES_SQL, add_descriptions_and_art
from .soundtracks import add_soundtracks


SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/handheld-retail"
REFERENCE = PROJECT_ROOT / "reference/handheld_retail.json"
NO_INTRO = "https://datomatic.no-intro.org/"
TOSEC = "https://www.tosecdev.org/"
REDUMP = "http://redump.org/discs/system/psp/"
LAUNCHBOX = "https://gamesdb.launchbox-app.com/"
MAME_HANDHELD = "https://raw.githubusercontent.com/mamedev/mame/mame0285/src/mame/handheld/hh_sm510.cpp"

MAME_LISTS = {
    "lynx": "lynx", "wonderswan": "wswan", "wonderswancolor": "wscolor", "pocketchallengev2": "pockchalv2",
    "pocketchallengew": "pockchalw", "gamate": "gamate", "gamepock": "gamepock", "gp32": "gp32", "gamemaster": "gmaster",
    "leapster": "leapster", "gb": "gameboy", "gbc": "gbcolor", "gba": "gba", "gamegear": "gamegear",
    "vmu": "svmu", "ngp": "ngp", "ngpc": "ngpc", "gamecom": "gamecom", "gameking": "gameking",
    "gameking3": "gameking3", "supervision": "svision", "megaduck": "megaduck",
}
LAUNCHBOX_PLATFORMS = {
    "lynx": "Atari Lynx", "wonderswan": "WonderSwan", "wonderswancolor": "WonderSwan Color", "gp32": "GamePark GP32",
    "gamewatch": "Nintendo Game & Watch", "gb": "Nintendo Game Boy", "gbc": "Nintendo Game Boy Color",
    "gba": "Nintendo Game Boy Advance", "nds": "Nintendo DS", "dsi": "Nintendo DSi", "3ds": "Nintendo 3DS",
    "pokemini": "Nintendo Pokemon Mini", "ngage": "Nokia N-Gage", "gamegear": "Sega Game Gear",
    "ngp": "SNK Neo Geo Pocket", "ngpc": "SNK Neo Geo Pocket Color", "psp": "Sony PSP", "psvita": "Sony Playstation Vita",
    "pocketstation": "Sony PocketStation", "gamecom": "Tiger Game.com", "supervision": "Watara Supervision",
}
# Platforms with an original software catalog distributed as downloads or through a host console.
DOWNLOAD_PLATFORMS = {"analoguepocket", "pece", "cybiko", "cybikoxtreme", "pandora", "playdate", "vmu", "pocketstation"}
TOSEC_SCOPES = {
    "analoguepocket": ("Analogue Pocket - Games",),
    "pece": ("Aquaplus P-ECE - Games",),
    "cybiko": ("Cybiko Cybiko - Games", "Cybiko Cybiko - Educational"),
    "cybikoxtreme": ("Cybiko Xtreme - Games",),
    "pandora": ("OpenPandora Pandora - Games",),
    "playdate": ("Panic Playdate - Games",),
    "vmu": ("Sega Visual Memory System - Games",),
    "pocketstation": ("Sony PocketStation - Games", "Sony PocketStation - Various"),
    "gameking": ("TimeTop GameKing - Games", "TimeTop GameKing - Compilations - Games"),
    "gameking3": ("TimeTop GameKing 3 - Games",),
    "gp32": ("Game Park GP32 - Games - [SMC]",),
    "gamemaster": ("Hartung Game Master - Games",),
}
NO_INTRO_SCOPES = {
    "gba": ("Nintendo - Game Boy Advance",), "nds": ("Nintendo - Nintendo DS (Decrypted)",),
    "dsi": ("Nintendo - Nintendo DSi (Decrypted)",),
}
JAPAN_ONLY = {"pece", "designmaster", "wonderswan", "wonderswancolor", "pocketchallengev2", "pocketchallengew",
              "gamepock", "pocketstation"}
COUNTRIES = {**COUNTRY_MARKETS, "Eur": "PAL", "Euro": "PAL", "Aus": "PAL", "Jpn": "JP", "Fra": "PAL", "Ger": "PAL", "Ita": "PAL",
             "BR": "BR", "Brazil": "BR", "LATIN_AMERICA": "LA", "Latin America": "LA",
             "KR": "KR", "Korea": "KR", "South Korea": "KR", "CN": "AS", "China": "AS", "TW": "AS",
             "Taiwan": "AS", "HK": "AS", "Hong Kong": "AS", "Asia": "AS", "AS": "AS", "RU": "PAL",
             "Russia": "PAL", "DK": "PAL", "NO": "PAL", "FI": "PAL", "GR": "PAL", "BE": "PAL",
             "PT": "PAL", "AT": "PAL", "CH": "PAL", "WORLD": "WORLD", "World": "WORLD"}
MARKETS = {market: {region for region, scope in COUNTRIES.items() if market == scope}
           for market in ("NA", "PAL", "JP", "KR", "AS", "BR", "LA", "WORLD", "UNK")}
DEVELOPMENT = re.compile(r"\((?:[^)]*, )?(?:prototype|proto|beta|alpha|demo|preview|unreleased|sampler|trial|sample|kiosk|test|"
                         r"hack|bootleg|pirate|homebrew|unl|unlicensed)(?:\b|\))|^\[(?:bios|firmware|bad dump)\]", re.I)
SUFFIX = re.compile(r"\s+\(([^()]*)\)$")
GAME_WATCH = re.compile(
    r'^SYST\(\s*(\d{4}),\s*(gnw_\w+)\s*,[^\n]*?"Nintendo"\s*,\s*"(?:Game & Watch|Micro Vs\. System): ([^"]+)"',
    re.M,
)
WATCH_EDITIONS = re.compile(r"\s+\((?:Silver|Gold|Wide Screen|New Wide Screen|Table Top|Panorama Screen|"
                            r"Multi Screen|[^()]+ version|version [^()]+)\)$")

LOCAL_RELEASES = text(f"""
    SELECT release.display_title AS title, title.display_title AS "preferredTitle",
           software.id AS "softwareId", {retail.SOFTWARE_KEY_SQL} AS "softwareKey",
           dat.dat_name AS dataset, dat.dat_path AS "datasetPath", signature.sha1_set_digest AS signature,
           package.source_collection AS collection, arrays.*,
           facts.regions, facts.versions, facts.revisions, facts.year, facts.publisher, facts.developer,
           facts.nintendo_power
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    JOIN catalog.software_release membership ON membership.software_id = software.id
    JOIN catalog.release release ON release.id = membership.release_id
    JOIN derived.dat dat ON dat.id = release.source_dat_id
    LEFT JOIN catalog.release_content_signature signature ON signature.release_id = release.id
    JOIN LATERAL (
        SELECT min(p.source_collection) AS source_collection
        FROM catalog.release_package part
        JOIN catalog.package p ON p.id = part.package_id
        WHERE part.release_id = release.id
        HAVING count(*) > 0 AND bool_and(p.source_collection IN ('No-Intro', 'Redump', 'TOSEC'))
    ) package ON true
    JOIN LATERAL (
        SELECT array_agg(p.archive_name ORDER BY part.media_sequence, p.archive_name) AS "archiveNames",
               jsonb_agg(jsonb_strip_nulls(jsonb_build_object('name', p.archive_name, 'number', part.media_sequence,
                         'label', coalesce(nullif(part.media_description, ''), nullif(part.media_label, ''))))
                         ORDER BY part.media_sequence, p.archive_name) AS discs,
               bool_and(p.resolved_path IS NOT NULL AND files.verified AND NOT EXISTS (
                   SELECT FROM derived.tag_classification tag
                   WHERE tag.archive_name_id = part.source_archive_name_id AND tag.record_index = part.source_record_index
                     AND tag.classification_status <> 'classified'
                     AND NOT coalesce(tag.value = ANY(:reviewed_tags) OR tag.value ~ :reviewed_serial, false)
               )) AS verified,
               CASE WHEN count(*) = 1 THEN min(files.program) END AS program
        FROM catalog.release_package part
        JOIN catalog.package p ON p.id = part.package_id
        JOIN LATERAL (
            SELECT count(*) > 0 AND bool_and(sha1_verified AND sha1_hex IS NOT NULL) AS verified,
                   CASE WHEN count(*) = 1 AND bool_and(sha1_verified) THEN min(sha1_hex) END AS program
            FROM catalog.package_file file WHERE file.package_id = p.id
        ) files ON true
        WHERE part.release_id = release.id
        HAVING release.expected_media_parts IS NULL OR
               (count(DISTINCT part.media_sequence) = release.expected_media_parts
                AND min(part.media_sequence) = 1 AND max(part.media_sequence) = release.expected_media_parts)
    ) arrays ON true
    JOIN LATERAL (
        SELECT coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value) FILTER (WHERE fact_key = 'region'), '{{}}') AS regions,
               coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value) FILTER (WHERE fact_key = 'version'), '{{}}') AS versions,
               coalesce(array_agg(DISTINCT fact_value ORDER BY fact_value) FILTER (WHERE fact_key = 'revision'), '{{}}') AS revisions,
               max(fact_value) FILTER (WHERE fact_key IN ('release_date', 'year')) AS year,
               max(fact_value) FILTER (WHERE fact_key = 'publisher') AS publisher,
               max(fact_value) FILTER (WHERE fact_key = 'developer') AS developer,
               bool_or(fact_key = 'special' AND fact_value = 'NP') AS nintendo_power
        FROM catalog.release_fact WHERE release_id = release.id
        HAVING NOT coalesce(bool_or(fact_key IN ('bios', 'demo', 'release_status', 'dump_modification')
                       OR (fact_key = 'dump_status' AND fact_value <> 'verified')
                       OR (fact_key = 'distribution_channel' AND fact_value <> 'nintendo_power')
                       OR (fact_key = 'license' AND fact_value = 'unlicensed' AND NOT :independent)), false)
    ) facts ON true
    WHERE system.manufacturer_name = :manufacturer AND system.system_name = :system
      AND release.grouping_status <> 'media_ambiguous'
      AND (package.source_collection = 'Redump'
           OR (package.source_collection = 'No-Intro' AND (NOT :select_nointro OR dat.dat_name = ANY(:no_intro)))
           OR (package.source_collection = 'TOSEC' AND dat.dat_name = ANY(:tosec)))
    ORDER BY release.display_title, arrays."archiveNames", release.id
""")

def _key(platform, *values):
    return sha256("\0".join((f"gamedb:{platform}-retail", *values)).encode()).hexdigest()[:32]


def _name(value):
    # DATs put leading articles after the title, including before a subtitle.
    return re.sub(r"^(.+?), (The|An|A)(?=$| - |:)", r"\2 \1", value.strip(), count=1, flags=re.I)


def _names(value):
    return list(dict.fromkeys(_name(part) for part in value.split(" ~ ") if part.strip()))


def _territories(value):
    return [region.strip() for region in re.split(r"[,/]", value) if region.strip()]


def _strip_regions(value):
    if (suffix := SUFFIX.search(value)) and all(region in COUNTRIES for region in _territories(suffix[1])):
        return value[:suffix.start()], _territories(suffix[1])
    return value, []


def _market_defaults(platform):
    return "JP" if platform in JAPAN_ONLY else "UNK"


def _date(value):
    return value if value and re.fullmatch(r"(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?", value) else ""


def _channel(platform, *, collection=None, nintendo_power=False):
    if platform == "gamewatch":
        return "built-in"
    if platform in DOWNLOAD_PLATFORMS:
        return "download"
    if nintendo_power:
        return "nintendo-power"
    if collection == "Redump":
        return "optical-disc"
    if platform in {"psp", "psvita", "3ds"} and collection is None:
        return "unknown"
    return "cartridge"


class HandheldCatalog:
    def __init__(self, platform, reference):
        self.platform = platform
        self.games = {}
        self.names = defaultdict(set)
        self.programs = defaultdict(set)
        self.codes = defaultdict(set)
        self.sources = {}
        self.launchbox = {}
        self.archive_count = 0
        self.roster = {title_key(name): title for title, aliases in reference.get("roster", {}).items()
                       for name in (title, *aliases)}

    def _add_names(self, game, names, markets):
        for name in names:
            self.names[title_key(name)].add(game["key"])
            if name != game["title"]:
                alias = {"title": name, "regions": sorted(markets)}
                if alias not in game["aliases"]:
                    game["aliases"].append(alias)

    def _new_game(self, name, identity):
        key = _key(self.platform, "game", identity)
        game = {"key": key, "title": name, "aliases": [], "publisher": "", "developer": "", "releases": {}}
        self.games[key] = game
        return game

    def find(self, names, *, program=None, market=None):
        if program and len(self.programs[program]) == 1:
            return self.games[next(iter(self.programs[program]))]
        candidates = set().union(*(self.names.get(title_key(name), ()) for name in names))
        if market and len(candidates) > 1:
            scoped = {key for key in candidates if any(release["market"] == market
                                                      for release in self.games[key]["releases"].values())}
            if scoped:
                candidates = scoped
        return self.games[next(iter(candidates))] if len(candidates) == 1 else None

    def add(self, names, regions, source, *, channel, game=None, identity=None, program=None, archive=None,
            publisher="", developer="", date="", codes=(), edition=None, artwork=None, known_release=True):
        if self.roster:
            titles = {self.roster[title_key(name)] for name in names if title_key(name) in self.roster}
            if len(titles) != 1:
                return None
            title, = titles
            names = list(dict.fromkeys([title, *names]))
            game = self.find([title])
            identity = title_key(title)
        markets = {COUNTRIES[region] for region in regions if region in COUNTRIES} or {_market_defaults(self.platform)}
        if game is None:
            identity = identity or title_key(names[0])
            game = self.games.get(_key(self.platform, "game", identity)) or self._new_game(names[0], identity)
        self._add_names(game, names, markets)
        if program:
            self.programs[program].add(game["key"])
        source_key = source["name"], source.get("index") or source.get("revision") or source["url"]
        self.sources.setdefault(source_key, source)
        for market in sorted(markets):
            # Higher quality sources can fill metadata without introducing a second release in the same market.
            previous = next((release for release in game["releases"].values()
                             if release["market"] == market and release["channel"] == channel
                             and (edition is None or release["edition"] == edition)), None)
            if not known_release and not previous:
                continue
            edition_name = edition or game["title"]
            if previous is None:
                key = _key(self.platform, "release", game["key"], edition_name, market, channel)
                previous = game["releases"][key] = {
                    "key": key, "edition": edition_name, "market": market, "channel": channel, "titles": [],
                    "source": source, "date": "", "developer": "", "publisher": "", "creditSources": {},
                    "status": "unmatched",
                }
            for name in names:
                if name not in previous["titles"]:
                    previous["titles"].append(name)
            if date and not previous["date"]:
                previous["date"] = date
                previous["dateSource"] = source
            for field, value in (("publisher", publisher), ("developer", developer)):
                if value and not previous[field]:
                    previous[field] = value
                    previous["creditSources"][field] = source
            if codes:
                previous["productCodes"] = sorted(set(previous.get("productCodes", ())) | set(codes))
                for code in codes:
                    self.codes[market, code].add(game["key"])
            if artwork:
                existing = previous.setdefault("artwork", {})
                for kind, asset in artwork.items():
                    existing.setdefault(kind, asset)
            if archive is not None:
                signatures = previous.setdefault("archives", {})
                signatures.setdefault(archive["signature"], archive)
                previous["status"] = "matched"
        return game

    def payload(self):
        games = sorted(self.games.values(), key=lambda game: (game["title"].casefold(), game["key"]))
        for game in games:
            releases = list(game["releases"].values())
            if len(releases) > 1:
                releases = [release for release in releases if release["market"] != "UNK" or release["status"] == "matched"]
            for release in releases:
                if artwork := game.get("sourceArtwork"):
                    images = release.setdefault("artwork", {})
                    for kind, asset in artwork.items():
                        images.setdefault(kind, asset)
                if archives := release.get("archives"):
                    release["archives"] = sorted(archives.values(), key=lambda archive: (archive["archiveNames"], archive["signature"]))
            game.pop("sourceArtwork", None)
            game["releases"] = releases
        games = [game for game in games if game["releases"]]
        sources = list(self.sources.values())
        primary = next((source for source in sources if source["name"] in {"MAME", "Nintendo", "Panic"}), None)
        if not primary and sources:
            primary = sources[0]
        catalog = {"source": primary, "releaseSources": sources, "games": games}
        retail.summarize_matches(catalog, self.archive_count, MARKETS)
        return catalog


def _local_games(connection, builder):
    platform = builder.platform
    manufacturer, system, _ = retail.HANDHELD_SYSTEMS[platform]
    params = {"manufacturer": manufacturer, "system": system, "select_nointro": platform in NO_INTRO_SCOPES,
              "no_intro": list(NO_INTRO_SCOPES.get(platform, ())),
              "tosec": list(TOSEC_SCOPES.get(platform, ())), "independent": platform in DOWNLOAD_PLATFORMS,
              "reviewed_tags": ["Design Cartridges"] if platform == "designmaster" else [],
              # Benesse cartridge product codes can appear as untyped DAT tags.
              "reviewed_serial": r"^[0-9][A-Z]{2}[0-9]{3}[A-Z]{0,3}$" if platform.startswith("pocketchallenge") else None}
    rows = connection.execute(LOCAL_RELEASES, params).mappings()
    software = {}
    for row in rows:
        raw_title = row["title"]
        if DEVELOPMENT.search(raw_title) or any(DEVELOPMENT.search(name) for name in row["archiveNames"]):
            continue
        if platform == "pokemini" and any("GameCube" in name for name in row["archiveNames"]):
            continue
        if platform == "psp" and re.search(r"^(?:sampler disc|game demo)\b", raw_title, re.I):
            continue
        if platform == "pocketstation" and row["dataset"].endswith(" - Various") and not any(
            re.search(r"\[[^]]*(?:Pocket MuuMuu|Doko Demo Issho|Final Fantasy|Chocobo|Digimon|Crash|Rockman)[^]]*\]", name, re.I)
            for name in row["archiveNames"]
        ):
            continue
        collection = row["collection"]
        source = {"name": collection, "url": {"No-Intro": NO_INTRO, "TOSEC": TOSEC, "Redump": REDUMP}[collection],
                  "record": row["datasetPath"].rsplit("/", 1)[-1]}
        channel = _channel(platform, collection=collection, nintendo_power=row["nintendo_power"])
        names = _names(raw_title)
        preferred = _names(row["preferredTitle"])
        # Start from the verified release label when the archive inventory's preferred language differs.
        if set(names).intersection(preferred):
            names = list(dict.fromkeys([*preferred, *names]))
        archive = None
        if row["verified"] and row["signature"]:
            archive = {field: row[field] for field in ("title", "softwareId", "softwareKey", "signature", "archiveNames",
                                                       "regions", "versions", "revisions")}
            archive.update(channel=channel, basis="verified-dat-content", evidence=source["record"])
            if channel == "optical-disc":
                archive["discs"] = row["discs"]
        regions = row["regions"]
        edition = "Nintendo Power" if channel == "nintendo-power" else None
        game = software.get(row["softwareKey"])
        if game is None:
            game = builder.find(names, program=row["program"])
        game = builder.add(names, regions, source, channel=channel, game=game, program=row["program"], archive=archive,
                           publisher=row["publisher"] or "", developer=row["developer"] or "", date=_date(row["year"]),
                           edition=f"{names[0]} ({edition})" if edition else None)
        if game is not None:
            software[row["softwareKey"]] = game
            builder.archive_count += archive is not None


def _mame_games(builder, index, list_name, artwork_sources, excluded_records=()):
    source = {"name": "MAME", "url": index.url, "revision": "mame0285", "sha256": index.digest}
    hierarchy = {}
    root = ElementTree.fromstring(index.content)
    if root.get("name") != list_name:
        raise ValueError(f"Unexpected MAME software list {list_name}")
    for record in root.findall("software"):
        description = record.findtext("description")
        category = record.findtext("publisher", "").casefold().strip("<>")
        if (record.get("name") in excluded_records or DEVELOPMENT.search(description)
                or re.search(r"^demo |\bdemo$", description, re.I)
                or category in {"homebrew", "unknown", "bootleg", "pirate", "unlicensed"}):
            continue
        if builder.platform == "pokemini" and re.search(r"\([^)]*\bGameCube\b", description, re.I):
            continue
        title, regions = _strip_regions(description)
        if not regions and builder.platform in {"gb", "gbc", "gba", "gamegear", "lynx"}:
            # For large software lists, an unscoped record only enriches a known program (below).
            append = record.get("cloneof") is None and record.find("info[@name='serial']") is not None
        else:
            append = True
        info = defaultdict(list)
        for item in record.findall("info"):
            info[item.get("name")].append(item.get("value"))
        digests = {rom.get("sha1") for rom in record.findall(".//rom[@sha1]") if rom.get("status") != "baddump"}
        digest = next(iter(digests)) if len(digests) == 1 else None
        date = next((f"{value[:4]}-{value[4:6]}-{value[6:8]}" for value in info["release"]
                     if re.match(r"^\d{8}\b", value) and value[4:6] != "00" and value[6:8] != "00"), None)
        names = [*_names(title), *info["alt_title"]]
        game = builder.find(names, program=digest) or hierarchy.get(record.get("cloneof"))
        if not game and not append:
            continue
        channel = _channel(builder.platform)
        if builder.platform == "vmu" and info["source"]:
            channel = "host-game"
        shortname = record.get("name")
        artwork = {
            kind: {
                "url": f"/media/catalog/{builder.platform}/{shortname}-{kind}-{pack['sha256'][:10]}.png",
                "source": {"name": "progetto-SNAPS", "url": pack["url"], "sha256": pack["sha256"]},
                "basis": "mame-software-list", "regions": regions,
            } for kind, pack in artwork_sources.items() if shortname in pack["records"]
        }
        game = builder.add(names, regions, {**source, "record": shortname}, channel=channel, game=game,
                           program=digest, publisher=record.findtext("publisher", ""),
                           date=date or _date(record.findtext("year")),
                           codes=[code.strip() for value in info["serial"] for code in value.split(",") if code.strip()],
                           artwork=artwork, known_release=append or bool(regions))
        if game is not None:
            hierarchy[shortname] = game
            if artwork and not regions:
                fallback = game.setdefault("sourceArtwork", {})
                for kind, asset in artwork.items():
                    fallback.setdefault(kind, asset)


def _game_watch(builder, index):
    source = {"name": "MAME", "url": index.url, "revision": "mame0285", "sha256": index.digest}
    for year, driver, edition in GAME_WATCH.findall(index.content.decode()):
        title = WATCH_EDITIONS.sub("", edition)
        game = builder.find([title])
        builder.add([title], [], {**source, "record": driver}, channel="built-in", game=game,
                    date=year, publisher="Nintendo", edition=edition)


def _add_launchbox(connection, builder, platform):
    if not connection.exec_driver_sql("SELECT to_regclass('staging.launchbox_import') IS NOT NULL").scalar_one():
        return
    snapshot = connection.execute(text("""
        SELECT id, source_revision FROM staging.launchbox_import ORDER BY imported_at DESC, id DESC LIMIT 1
    """)).one_or_none()
    if snapshot is None:
        return
    releases, alternate_names = {}, defaultdict(list)
    for row in connection.execute(LAUNCHBOX_GAMES_SQL, {"snapshot": snapshot.id, "platforms": [platform]}):
        if row.record_type == "Game" and row.raw_record.get("ReleaseType") == "Released":
            releases[row.database_id] = row.raw_record
        elif row.record_type == "GameAlternateName" and (alias := row.raw_record.get("AlternateName")):
            alternate_names[row.database_id].append(alias)
    counts = Counter(title_key(record["Name"]) for record in releases.values())
    genres = read_genre_aliases(PROJECT_ROOT / "reference/genre_aliases.csv")
    for database_id, record in sorted(releases.items()):
        name = record["Name"].strip()
        if (not name or DEVELOPMENT.search(name) or re.search(r"^(?:sampler disc|game demo)\b", name, re.I)
                or (builder.platform == "gamewatch" and not name.startswith("Game & Watch:"))):
            continue
        if builder.platform == "gamewatch":
            name = name.removeprefix("Game & Watch:").strip()
        names = [name, *alternate_names[database_id]]
        game = builder.find([name]) if counts[title_key(record["Name"])] == 1 else None
        if game is None and counts[title_key(record["Name"])] == 1:
            game = builder.find(names)
        if game is None and builder.platform == "gamewatch":
            continue  # MAME documents the original Nintendo units; LaunchBox also lists other LCD makers.
        source = {"name": "LaunchBox", "url": LAUNCHBOX, "revision": snapshot.source_revision, "record": database_id}
        if game:
            builder._add_names(game, names, ())
        else:
            game = builder.add(names, [], source, channel=_channel(builder.platform),
                               identity=f"launchbox:{database_id}", publisher=record.get("Publisher", ""),
                               developer=record.get("Developer", ""), date=_date(record.get("ReleaseDate")))
        if game is not None:
            builder.launchbox.setdefault(game["key"], database_id)
            if record.get("Genres"):
                game.setdefault("genres", genre_values(record["Genres"], "launchbox", genres))


def _source_index(directory, name, url, indexes, warnings):
    try:
        index = indexes[name] = read_index(directory / name, url)
    except (OSError, ValueError) as error:
        warnings.append(f"{name}: {error}")
        return None
    return index


def apply_handheld_retail_review(catalog, reference):
    review = reference.get("retailReview", {})
    if not review:
        return {}
    excluded_records = set(review.get("mameRecords", ()))
    excluded_titles = set(review.get("excludedTitles", ()))
    games = catalog["games"]
    before = sum(len(game["releases"]) for game in games)
    archive_count = catalog["summary"]["eligibleArchives"]
    kept = []
    for game in games:
        releases = []
        for release in game["releases"]:
            source = release["source"]
            if game["title"] in excluded_titles or (source["name"] == "MAME" and source.get("record") in excluded_records):
                archive_count -= len(release.get("archives", ()))
            else:
                releases.append(release)
        if releases:
            game["releases"] = releases
            kept.append(game)
    removed_releases = before - sum(len(game["releases"]) for game in kept)
    by_title = defaultdict(list)
    for game in kept:
        by_title[game["title"]].append(game)
    merged = set()
    for duplicate, canonical in review.get("mergedTitles", {}).items():
        if len(by_title[duplicate]) != 1 or len(by_title[canonical]) != 1:
            continue
        former, = by_title[duplicate]
        target, = by_title[canonical]
        target.setdefault("formerKeys", []).extend([former["key"], *former.get("formerKeys", ())])
        for alias in [{"title": duplicate, "regions": []}, *former.get("aliases", ())]:
            if alias["title"] != canonical and alias not in target["aliases"]:
                target["aliases"].append(alias)
        target["releases"].extend(former["releases"])
        for field in ("soundtrackLinks", "soundtrackSources"):
            if former.get(field):
                sources = target.setdefault(field, [])
                sources.extend(item for item in former[field] if item not in sources)
        merged.add(former["key"])
    kept = [game for game in kept if game["key"] not in merged]
    if not (removed_releases or merged):
        return {}
    catalog["games"] = kept
    summary = catalog["summary"]
    retail.summarize_matches(catalog, archive_count, MARKETS)
    summary.update(catalog["summary"])
    catalog["summary"] = summary
    if "metadata" in summary:
        summary["metadata"] = retail.enrichment_coverage(catalog, MARKETS)
    if "mediaTitles" in summary:
        summary["mediaTitles"]["manuals"] = sum(
            any(release.get("manuals") for release in game["releases"]) for game in kept
        )
    return {"excludedTitles": len(games) - len(kept) - len(merged), "excludedReleases": removed_releases,
            "mergedTitles": len(merged)}


def seed_handheld(platform, report=None, *, publish_catalog=False, sources=None):
    from .handheld_artwork import artwork_sources, fill_handheld_artwork, thumbnail_root
    from .handheld_media import (THUMBNAILS, TRACK_FORMATS, add_handheld_manuals, add_handheld_soundtracks,
                                 add_handheld_sources, read_handheld_sources)

    ProjectEnvironment().load()
    directory = sources or SOURCE_DIRECTORY
    reference = json.loads(REFERENCE.read_text(encoding="utf-8")).get(platform, {})
    builder = HandheldCatalog(platform, reference)
    indexes, warnings = {}, []
    mame = MAME_LISTS.get(platform)
    mame_index = _source_index(directory, f"mame/{mame}.xml", f"{MAME_RAW}{mame}.xml", indexes, warnings) if mame else None
    watch = _source_index(directory, "gamewatch.cpp", MAME_HANDHELD, indexes, warnings) if platform == "gamewatch" else None
    if platform in THUMBNAILS:
        folder, revision = THUMBNAILS[platform]
        url = f"https://api.github.com/repos/libretro-thumbnails/{folder.replace(' ', '_')}/git/trees/{revision}?recursive=1"
        _source_index(directory, f"thumbs-{platform}.json", url, indexes, warnings)
    read_handheld_sources(platform, directory, indexes, warnings, _source_index)

    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            if publish_catalog:
                connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:catalog))"), {"catalog": f"gamedb.{platform}-retail"})
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            _local_games(connection, builder)
            if mame_index:
                _mame_games(builder, mame_index, mame, reference.get("mameArtwork", {}),
                            set(reference.get("retailReview", {}).get("mameRecords", ())))
            if watch:
                _game_watch(builder, watch)
            add_handheld_sources(builder, indexes, reference)
            launchbox = LAUNCHBOX_PLATFORMS.get(platform)
            if launchbox:
                _add_launchbox(connection, builder, launchbox)
            catalog = builder.payload()
            apply_handheld_retail_review(catalog, reference)
            if not catalog["games"]:
                raise ValueError(f"No documented releases found for {retail.HANDHELD_PLATFORMS[platform]}")
            catalog["enrichmentSources"] = [{"url": item.url, "sha256": item.digest} for item in indexes.values()]
            add_descriptions_and_art(connection, catalog, indexes, reference, platforms={launchbox} if launchbox else set(),
                                     thumbnails=THUMBNAILS, thumbnail_key=platform, country_markets=COUNTRIES,
                                     include_unmatched=True, known_launchbox=builder.launchbox)
            add_handheld_manuals(platform, catalog, indexes, reference)
            if variants := reference.get("prepatchedVariants"):
                catalog["summary"]["prepatchedVariants"] = add_disc_variants(
                    connection, catalog, retail.HANDHELD_SYSTEMS[platform][:2], MARKETS,
                    reviewed=variants, reviewed_only=True,
                    status="Prepatched UMD image" if platform == "psp" else "Prepatched game archive",
                )
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=retail.HANDHELD_SYSTEMS[platform][:2], secondary_platform=None,
                formats=TRACK_FORMATS, aliases=reference.get("soundtrackAliases", ()),
                joshw_archive_bucket=HANDHELD_BUCKETS.get(platform), include_unmatched=True,
            )
            catalog["summary"]["soundtrackSources"] = add_handheld_soundtracks(platform, catalog, indexes)
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, markets=MARKETS)
            catalog["summary"]["mediaTitles"] = {field: sum(any(release.get(field) for release in game["releases"])
                for game in catalog["games"]) for field in ("artwork", "manuals")}
            fill_handheld_artwork(catalog, platform, thumbnail_root(), artwork_sources().get(platform, {}))
            if warnings:
                catalog["summary"]["sourceWarnings"] = warnings
            if publish_catalog:
                retail.publish(connection, catalog, platform)
    finally:
        engine.dispose()
    if report:
        retail.write_report(report, catalog)
    return {"published": publish_catalog, **catalog["summary"]}
