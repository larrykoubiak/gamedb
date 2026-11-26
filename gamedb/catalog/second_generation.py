"""Build original retail catalogs for early cartridge consoles."""

from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import text

from gamedb.config import PROJECT_ROOT
from gamedb.database import create_database_engine

from . import retail
from .cartridges import COUNTRY_MARKETS, VERIFIED_ROM_SQL
from .megadrive import add_cartridge_details, cartridge_records
from .references import MAME_RAW, read_index
from .retail_media import _manual_key, add_descriptions_and_art, add_manuals, add_reviewed_artwork, release_names
from .soundtracks import add_soundtracks


REFERENCE = PROJECT_ROOT / "reference" / "second_generation_retail.json"
ADDITIONAL_REFERENCE = REFERENCE.with_name("additional_cartridge_retail.json")
SOURCE_DIRECTORY = PROJECT_ROOT / "data/media/cache/second-generation-retail"
SYSTEMS = {
    "channelf": ("Fairchild", "Channel F"),
    "atari2600": ("Atari", "2600"),
    "atari5200": ("Atari", "5200"),
    "atari7800": ("Atari", "7800"),
    "xegs": ("Atari", "8-bit computers"),
    "odyssey2": ("Magnavox", "Odyssey 2"),
    "intellivision": ("Mattel", "Intellivision"),
    "colecovision": ("Coleco", "ColecoVision"),
    "astrocade": ("Bally", "Astrocade"), "arcadia": ("Emerson", "Arcadia 2001"),
    "vc4000": ("Interton", "VC 4000"), "studio2": ("RCA", "Studio II"), "creativision": ("VTech", "CreatiVision"),
    "vectrex": ("GCE", "Vectrex"), "advision": ("Entex", "Adventure Vision"), "pv1000": ("Casio", "PV-1000"),
    "scv": ("Epoch", "Super Cassette Vision"), "myvision": ("Nichibutsu", "My Vision"),
    "superacan": ("Funtech", "Super A'can"), "loopy": ("Casio", "Loopy"), "virtualboy": ("Nintendo", "Virtual Boy"),
    "pico": ("Sega", "Pico"), "copera": ("Yamaha", "Copera"), "picno": ("Konami", "Picno"), "vsmile": ("VTech", "V.Smile"),
    "gx4000": ("Amstrad", "GX4000"),
}
LAUNCHBOX = {
    "channelf": "Fairchild Channel F", "atari2600": "Atari 2600", "atari5200": "Atari 5200", "atari7800": "Atari 7800",
    "xegs": "Atari XEGS",
    "odyssey2": "Magnavox Odyssey 2", "intellivision": "Mattel Intellivision", "colecovision": "ColecoVision",
    **{key: " ".join(SYSTEMS[key]) for key in retail.ADDITIONAL_CARTRIDGE_PLATFORMS},
    "superacan": "Funtech Super Acan",
}
THUMBNAILS = {
    "channelf": ("Fairchild - Channel F", "f4463eafc549fe8dd371becc107a153f9d5e9b53"),
    "atari2600": ("Atari - 2600", "8c91fd5d4cdadb6e66e146ab5b5334aebd3c82e9"),
    "atari5200": ("Atari - 5200", "30b60c8a3bf2eff5c977ca09e909b9ef06a8c5c0"),
    "atari7800": ("Atari - 7800", "4e70623cfa172e618d2c44dd18625030a8670c40"),
    "odyssey2": ("Magnavox - Odyssey2", "6740e62db09fa268240247c3ba18cd9e4a2b957f"),
    "intellivision": ("Mattel - Intellivision", "502182a9802bc77a534b75f8d730bc48153fb6c8"),
    "colecovision": ("Coleco - ColecoVision", "d260c1e4f2840e03403c28f33f126ff1e09d7c35"),
    "arcadia": ("Emerson - Arcadia 2001", "3e099e570648484868c83520a9cce71680a4af72"),
    "studio2": ("RCA - Studio II", "fc594abc77c4cd1c9db11d9e0131e105b7f54b40"),
    "creativision": ("VTech - CreatiVision", "5e793f9e426bfa30b588704be49cf9833dd8b980"),
    "vectrex": ("GCE - Vectrex", "337252e121ec8cc3ca134c873b45d5b081a168e8"),
    "advision": ("Entex - Adventure Vision", "159846f40fab9d4452ee885d37cb7ad1509927ee"),
    "pv1000": ("Casio - PV-1000", "45f03515406bdd7a566b66e0a6312797e6ead5e9"),
    "scv": ("Epoch - Super Cassette Vision", "c5974b448b6ee2ad37f15b29e32e213d04100e9d"),
    "superacan": ("Funtech - Super Acan", "42814d92de3badeca39e9b0d613f4a2edc13bde1"),
    "loopy": ("Casio - Loopy", "f8579c29b9e68da2673cc0d1fa0cfd7d6fe147ab"),
    "virtualboy": ("Nintendo - Virtual Boy", "75693093d5c9bce8fc61ec073877384c47c82cb6"),
    "pico": ("Sega - PICO", "05941f83fcbd2885d2dc8fd3c24e4c11f44701f6"),
    "vsmile": ("VTech - V.Smile", "2dc4a0e0c28bc707b0eb384cba213ec54b835e2b"),
}
MAME_LISTS = {
    "channelf": ("channelf",), "atari2600": ("a2600",), "atari5200": ("a5200",), "atari7800": ("a7800",),
    "xegs": ("xegs", "a800"),
    "odyssey2": ("videopac",), "intellivision": ("intv", "intvecs"), "colecovision": ("coleco",),
    "astrocade": ("astrocde",), "arcadia": ("arcadia",), "vc4000": ("vc4000",), "studio2": ("studio2", "visicom"),
    "creativision": ("crvision",), "vectrex": ("vectrex",), "advision": ("advision",), "pv1000": ("pv1000",),
    "scv": ("scv",), "myvision": ("myvision",), "superacan": ("supracan",), "loopy": ("casloopy",),
    "virtualboy": ("vboy",), "pico": ("pico",), "copera": ("copera",), "picno": ("picno",), "vsmile": ("vsmile_cart",),
    "gx4000": ("gx4000",),
}
TOSEC_MANUALS = {
    "channelf": "Fairchild/VES & Channel F", "atari2600": "Atari/2600 & VCS", "atari5200": "Atari/5200",
    "atari7800": "Atari/7800", "xegs": "Atari/8bit",
    "odyssey2": "Magnavox/Odyssey2", "intellivision": "Mattel/Intellivision", "colecovision": "Coleco/ColecoVision",
    "astrocade": "Bally/Professional Arcade & Astrocade", "vectrex": "GCE/Vectrex", "virtualboy": "Nintendo/Virtual Boy",
}
MANUAL_SITES = {
    "atari2600": ("Digital Press", "https://www.digitpress.com/library/manuals/atari2600/index.html"),
    "atari7800": ("Digital Press", "https://www.digitpress.com/library/manuals/atari7800/index.html"),
    "odyssey2": ("The Odyssey² Homepage", "https://odyssey2.info/library/"),
}
MARKETS = {**retail.ARCHIVE_MARKETS, "BR": {"BR"}}
ADDITIONAL_MARKETS = {
    **MARKETS, "PAL": MARKETS["PAL"] | {"DK", "NL", "SE", "NO", "FI", "PT", "BE", "CH", "AT", "IT"},
    "AS": {"AS", "TW", "HK"}, "KR": {"KR"}, "WORLD": {"WORLD"},
}
DEFAULT_REGIONS = {"NA": "US", "PAL": "EU", "JP": "JP", "BR": "BR", "AS": "TW", "KR": "KR", "WORLD": "WORLD"}
COUNTRIES = {**COUNTRY_MARKETS, "BR": "BR", "Brazil": "BR", "PAL": "PAL", "TW": "AS",
             "Taiwan": "AS", "Asia": "AS", "KR": "KR", "Korea": "KR"}
PLUS = "videopac-plus"
VISICOM = "visicom"
TOSEC = "https://www.tosecdev.org/"
MANUAL_CLASSES = {"Games", "Educational", "Software", "Applications"}
XEGS_REISSUES = {"dkong", "eastfrnt"}

TOSEC_PROGRAMS = text(f"""
    SELECT software.id AS "softwareId", {retail.SOFTWARE_KEY_SQL} AS "softwareKey",
           content.sha1_set_digest AS signature, package.archive_name AS "archiveName",
           file.sha1_hex AS sha1, facts.regions, facts.video
    FROM catalog.system system
    JOIN catalog.software software ON software.system_id = system.id
    JOIN catalog.title title ON title.id = software.preferred_title_id
    JOIN catalog.software_release member ON member.software_id = software.id
    JOIN catalog.release_content_signature content ON content.release_id = member.release_id
    JOIN catalog.release_package part ON part.release_id = content.release_id
    JOIN catalog.package package ON package.id = part.package_id
    JOIN catalog.package_file file ON file.package_id = package.id
    JOIN LATERAL (
        SELECT coalesce(array_agg(fact_value) FILTER (WHERE fact_key = 'region'), '{{}}') AS regions,
               max(fact_value) FILTER (WHERE fact_key = 'video') AS video
        FROM catalog.release_fact
        WHERE release_id = content.release_id
        HAVING NOT bool_or(fact_key IN ('bios', 'demo', 'release_status', 'license', 'dump_modification')
            OR (fact_key = 'dump_status' AND fact_value <> ALL(CAST(:allowed_dump_status AS text[]))))
    ) facts ON true
    WHERE system.manufacturer_name = :manufacturer AND system.system_name = :system
      AND content.package_count = 1 AND content.rom_count = 1
      AND package.source_collection = 'TOSEC' AND package.resolved_path IS NOT NULL
      AND file.sha1_verified AND file.sha1_hex = ANY(CAST(:digests AS text[]))
    ORDER BY package.archive_name, content.sha1_set_digest
""")


def _key(platform, *parts):
    return sha256("\0".join((f"gamedb:{platform}-retail", *parts)).encode()).hexdigest()[:32]


def _new_release(platform, title, market, **fields):
    hardware = fields.get("hardware")
    edition = fields.get("edition", f"{title} (Videopac+)" if hardware == PLUS else title)
    return {
        "key": _key(platform, "release", edition, market), "edition": edition, "market": market,
        "titles": [title], "date": "", "channel": PLUS if hardware == PLUS else "cartridge",
        **fields,
    }


def build_catalog(platform, reference):
    source = reference["source"]
    if source["rowCount"] != len(reference["games"]):
        raise ValueError(f"Unexpected {platform} retail roster size")
    games = []
    for item in reference["games"]:
        title = item["title"]
        credits = {field: item.get(field, "") for field in ("developer", "publisher")}
        releases = [_new_release(platform, title, **{**credits, **fields}) for fields in item["releases"]]
        for release in releases:
            if platform in retail.ADDITIONAL_CARTRIDGE_PLATFORMS:
                release.setdefault("source", source)
            release["creditSources"] = {field: release.get("source", source) for field in credits if release[field]}
        games.append({"key": _key(platform, "game", title), "title": title, "aliases": [],
                      "releases": releases, **credits, **({"genre": item["genre"]} if item.get("genre") else {})})
    release_keys = [release["key"] for game in games for release in game["releases"]]
    if len(set(release_keys)) != len(release_keys) or any(not game["releases"] for game in games):
        raise ValueError(f"Duplicate or empty {platform} retail entry")
    catalog = {"source": source, "games": games}
    if platform == "odyssey2":
        catalog["addonSources"] = {PLUS: source}
    if addon_sources := reference.get("addonSources"):
        catalog.setdefault("addonSources", {}).update(addon_sources)
    return catalog


def _source_indexes(platform, directory):
    urls = {f"{name}.xml": f"{MAME_RAW}{name}.xml" for name in MAME_LISTS[platform]}
    if platform in THUMBNAILS:
        folder, revision = THUMBNAILS[platform]
        repository = folder.replace(" ", "_")
        urls[f"thumbs-{platform}.json"] = (
            f"https://api.github.com/repos/libretro-thumbnails/{repository}/git/trees/{revision}?recursive=1"
        )
    if manual_site := MANUAL_SITES.get(platform):
        urls["manuals.html"] = manual_site[1]
    indexes, issues = {}, []
    for filename, url in urls.items():
        try:
            indexes[filename] = read_index(directory / filename, url)
        except (OSError, ValueError) as error:
            issues.append(f"{filename}: {error}")
    return indexes, issues


def _archive_names(archive):
    return archive["title"].split(" ~ ")


def _observed_releases(platform, catalog, archives):
    """Add releases only when an independently listed title has an exact scoped archive."""
    if platform not in {"atari2600", "colecovision", "intellivision"}:
        return
    listed = defaultdict(dict)
    for game in catalog["games"]:
        for name in {game["title"], *(title for release in game["releases"] for title in release["titles"])}:
            listed[retail._title_key(name)][game["key"]] = game
    for archive in archives:
        owners = {key: game for name in _archive_names(archive) for key, game in listed[retail._title_key(name)].items()}
        if len(owners) != 1:
            continue
        (game,) = owners.values()
        existing = {release["market"] for release in game["releases"]}
        if "NA" not in existing:
            continue
        for market in ("PAL", "JP"):
            if market in existing or not MARKETS[market].intersection(archive["regions"]):
                continue
            game["releases"].append(_new_release(platform, game["title"], market,
                titles=[game["title"]], needsRegionEvidence=True))


def _reviewed_matches(catalog, archives, reference, markets):
    aliases = {(item["edition"], item["market"], retail._title_key(item["archiveTitle"])): item
               for item in reference.get("archiveAliases", ())}
    for game in catalog["games"]:
        for release in game["releases"]:
            scope = release["market"]
            titles = {retail._title_key(name) for name in release["titles"]}
            for archive in archives:
                if " ~ " not in archive["title"] or archive["channel"] != release["channel"]:
                    continue
                if not (markets[scope].intersection(archive["regions"]) or "WORLD" in archive["regions"]):
                    continue
                if titles.intersection(map(retail._title_key, _archive_names(archive))):
                    name = archive["title"]
                    aliases.setdefault((release["edition"], scope, retail._title_key(name)), {
                        "edition": release["edition"], "market": scope, "archiveTitle": name,
                        "evidence": "Alternate title from the same verified No-Intro archive",
                    })
    return list(aliases.values())


def _tosec_fallback(connection, platform, catalog, archives, records, *, headered_digests=None):
    # Reviewed fingerprints can identify cartridge programs stored in a container format.
    headered_digests = headered_digests or {}
    default_market = "PAL" if platform == "gx4000" else "NA"
    by_title = defaultdict(list)
    for record in records:
        for name in record.names:
            by_title[retail._compact_title(name)].append(record)
    title_counts = defaultdict(set)
    claimed = {}
    pending = []
    for game in catalog["games"]:
        for release in game["releases"]:
            if release["channel"] != "cartridge":
                continue
            names = {retail._compact_title(title) for title in release["titles"]}
            for name in names:
                title_counts[release["market"], name].add(release["edition"])
            if release["status"] == "unmatched":
                pending.append((release, names))
            for archive in release.get("archives", ()):
                claimed[archive["signature"]] = release["edition"]

    wanted = {record.digest for release, names in pending for name in names for record in by_title[name]
              if title_counts[release["market"], name] == {release["edition"]}
              and release["market"] in (record.markets or {default_market})}
    if not wanted:
        return {}
    known_signatures = {archive["signature"] for archive in archives}
    maker, system = SYSTEMS[platform]
    if platform == "gx4000":
        # TOSEC groups the retail GX4000 cartridge dumps under CPC.
        system = "CPC"
    packages = defaultdict(list)
    digests = {wrapped for wrapped, digest in headered_digests.items() if digest in wanted}
    if platform != "gx4000":
        digests.update(wanted)
    allowed_dump_status = ["verified", "alternate"] if platform in {"xegs", "gx4000"} else []
    for row in connection.execute(TOSEC_PROGRAMS, {"manufacturer": maker, "system": system,
                                                   "digests": sorted(digests),
                                                   "allowed_dump_status": allowed_dump_status}).mappings():
        if row["signature"] not in known_signatures:
            packages[headered_digests.get(row["sha1"], row["sha1"])].append(row)
    matches = {}
    for release, names in pending:
        market = release["market"]
        choices = {}
        for name in names:
            if title_counts[market, name] != {release["edition"]}:
                continue
            for record in by_title[name]:
                if market not in (record.markets or {default_market}):
                    continue
                for row in packages[record.digest]:
                    if claimed.get(row["signature"], release["edition"]) != release["edition"]:
                        continue
                    territories = {COUNTRIES[r] for r in row["regions"] if r in COUNTRIES}
                    if (territories and market not in territories) or (row["video"] == "NTSC" and market == "PAL"):
                        continue
                    evidence = record.evidence["source"]
                    fingerprint = "cartridge SHA-1"
                    if row["sha1"] != record.digest:
                        fingerprint += " of the CPR program banks" if platform == "gx4000" else " after CART header"
                    choices.setdefault(row["signature"], ({
                        "title": release["titles"][0], "archiveNames": [row["archiveName"]],
                        "signature": row["signature"], "softwareId": row["softwareId"], "softwareKey": row["softwareKey"],
                        "regions": row["regions"] or [DEFAULT_REGIONS[market]], "versions": [], "revisions": [],
                        "channel": "cartridge", "basis": "reviewed-content-and-region",
                        "evidence": f"{evidence['url']} ({evidence['record']}, {fingerprint})",
                    }, record.digest, record.group))
        if len({group for _, _, group in choices.values()}) != 1:
            continue
        release.update(status="matched", archives=[item[0] for _, item in sorted(choices.items())])
        for signature, (_, digest, _) in choices.items():
            claimed[signature] = release["edition"]
            matches[signature] = digest
    return matches


def _match(connection, platform, catalog, reference, indexes, markets):
    reviewed = reference.get("verifiedArchives", [])
    archives = retail.read_archives(connection, *SYSTEMS[platform], reviewed)
    corrected_regions = {item["signature"]: item["regions"] for item in reviewed if item.get("regions")}
    for archive in archives:
        if regions := corrected_regions.get(archive["signature"]):
            archive["regions"] = regions
    if platform == "odyssey2":
        archives.extend({**archive, "channel": PLUS} for archive in
                        retail.read_archives(connection, "Philips", "Videopac+"))
    elif platform == "studio2":
        archives.extend({**archive, "channel": VISICOM} for archive in
                        retail.read_archives(connection, "Toshiba", "Visicom", reviewed))
    records = [record for name in MAME_LISTS[platform] if (index := indexes.get(f"{name}.xml"))
               for record in cartridge_records(index.content, filename=f"{name}.xml", regions=COUNTRIES)
               if name != "a800" or record.evidence["source"]["record"] in XEGS_REISSUES]
    roms = {row.signature: row.sha1 for row in connection.execute(VERIFIED_ROM_SQL, {
        "signatures": [archive["signature"] for archive in archives],
    })}
    headered_digests = reference.get("headeredCartridgeDigests", {})
    if platform == "xegs":
        expected = {record.digest for record in records}
        roms = {signature: headered_digests.get(digest, digest) for signature, digest in roms.items()}
        archives = [archive for archive in archives if roms.get(archive["signature"]) in expected]
    _observed_releases(platform, catalog, archives)
    aliases = _reviewed_matches(catalog, archives, reference, markets)
    for game in catalog["games"]:
        for release in game["releases"]:
            for title in release["titles"]:
                alias = {"title": title, "regions": [release["market"]]}
                if title != game["title"] and alias not in game["aliases"]:
                    game["aliases"].append(alias)
    retail.match_archives(catalog, archives, aliases, reviewed, markets=markets)
    if platform != "odyssey2":
        supplemental = list(retail.cartridge_group_matches(catalog, archives, roms, records, markets=markets))
        if supplemental:
            retail.match_archives(catalog, archives, aliases, [*reviewed, *supplemental], markets=markets)
    fallback = _tosec_fallback(connection, platform, catalog, archives, records, headered_digests=headered_digests)
    roms.update(fallback)
    for game in catalog["games"]:
        good = [release for release in game["releases"]
                if not release.get("needsRegionEvidence") or release["status"] == "matched"]
        game["releases"] = good or game["releases"][:1]
        for release in game["releases"]:
            release.pop("needsRegionEvidence", None)
    retail.summarize_matches(catalog, len(archives) + len(fallback), markets)
    add_cartridge_details(catalog, roms, records, markets=markets)


def _tosec_manuals(platform):
    if platform not in TOSEC_MANUALS:
        return
    root = Path(os.environ.get("GAMEDB_ROM_ROOT") or "/mnt/synology") / "roms/TOSEC-PIX"
    directory = root / TOSEC_MANUALS[platform] / "Manuals"
    for file in sorted(directory.glob("*/*.zip")):
        if file.parent.name not in MANUAL_CLASSES:
            continue
        match = re.fullmatch(r"(.+?) \((?:19\d[\dx])(?:-\d{2}){0,2}\)\([^)]*\)((?:\([^)]*\)|\[[^\]]*\])*)", file.stem)
        if match is None:
            continue
        name, labels = match.groups()
        labels = re.findall(r"\(([^)]+)\)", labels)
        countries = [label for label in labels if label in COUNTRIES]
        markets = {COUNTRIES[label] for label in countries}
        if len(markets) > 1:
            continue
        local_archive = file.relative_to(root).as_posix()
        yield name, next(iter(markets), "NA"), {
            "format": "PDF", "localArchive": local_archive, "source": "TOSEC PIX",
            "url": f"{TOSEC}#pix/{quote(local_archive)}",
            "sourceUrl": TOSEC, "regions": countries,
        }


def _online_manuals(platform, index):
    source, base = MANUAL_SITES[platform]
    soup = BeautifulSoup(index.content, "html.parser")
    for link in soup.select("a[href]"):
        href = link["href"]
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or not parsed.path.lower().endswith(".pdf"):
            continue
        if source == "Digital Press":
            row = link.find_parent("tr")
            cell = row.find("td") if row is not None else None
            if cell is None:
                continue
            name = cell.get_text(" ", strip=True).strip()
            market = "PAL" if re.search(r"\((?:PAL|Europe)\)$", name, flags=re.I) else "NA"
            name = re.sub(r"\s*\((?:PAL|Europe)\)$", "", name, flags=re.I)
        else:
            filename = unquote(Path(parsed.path).stem)
            if not filename.endswith(" (USA)"):
                continue
            name, market = filename.removesuffix(" (USA)"), "NA"
        yield name, market, {
            "format": "PDF", "url": urljoin(base, quote(unquote(href), safe="/%")),
            "source": source, "sourceUrl": base, "regions": ["EUR" if market == "PAL" else "US"],
        }


def _manual_matches(platform, catalog, reference, index):
    scopes = defaultdict(dict)
    for game in catalog["games"]:
        for release in game["releases"]:
            if release["status"] != "matched":
                continue
            names = {*release_names(release), *release.get("productCodes", ())}
            names.update(title for archive in release["archives"] for title in _archive_names(archive))
            for name in names:
                scopes[release["market"], _manual_key(name)][release["key"]] = release
    for alias in reference.get("manualAliases", ()):
        release = next((release for game in catalog["games"] for release in game["releases"]
                        if release["edition"] == alias["edition"] and release["market"] == alias["market"]), None)
        if release and release["status"] == "matched":
            scopes[alias["market"], _manual_key(alias["title"])][release["key"]] = release

    linked = set()
    candidates = list(_tosec_manuals(platform))
    if index:
        candidates.extend(_online_manuals(platform, index))
    for title, market, manual in candidates:
        items = scopes[market, _manual_key(title)]
        if len(items) != 1:
            continue
        (release,) = items.values()
        if release["key"] not in linked:
            linked.add(release["key"])
            yield {"edition": release["edition"], "market": market, "name": f"{release['titles'][0]} — manual", **manual}
    yield from reference.get("manuals", ())


def seed_cartridge(platform, report=None, *, publish_catalog=False, sources=None):
    markets = MARKETS
    if platform in retail.SECOND_GENERATION_PLATFORMS:
        reference = json.loads(REFERENCE.read_text(encoding="utf-8"))[platform]
        source_directory = SOURCE_DIRECTORY / platform
    elif platform in retail.ADDITIONAL_CARTRIDGE_PLATFORMS:
        reference = json.loads(ADDITIONAL_REFERENCE.read_text(encoding="utf-8"))[platform]
        source_directory = SOURCE_DIRECTORY.parent / f"{platform}-retail"
        markets = ADDITIONAL_MARKETS
    else:
        reference = json.loads((REFERENCE.parent / f"{platform}_retail.json").read_text(encoding="utf-8"))
        source_directory = SOURCE_DIRECTORY.parent / f"{platform}-retail"
    catalog = build_catalog(platform, reference)
    indexes, issues = _source_indexes(platform, sources or source_directory)
    catalog["enrichmentSources"] = [
        *reference.get("additionalSources", ()), *({"url": source.url, "sha256": source.digest} for source in indexes.values()),
    ]
    engine = create_database_engine()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            connection.exec_driver_sql(f"SELECT pg_advisory_xact_lock(hashtext('gamedb.{platform}-retail'))"
                                       if publish_catalog else "SET TRANSACTION READ ONLY")
            _match(connection, platform, catalog, reference, indexes, markets)
            add_descriptions_and_art(connection, catalog, indexes, reference,
                                     platforms={LAUNCHBOX[platform], *({"Philips Videopac+"} if platform == "odyssey2" else ())},
                                     thumbnails=THUMBNAILS, thumbnail_key=platform, country_markets=COUNTRIES)
            if artwork := reference.get("reviewedArtwork"):
                add_reviewed_artwork(catalog, platform, indexes, artwork, thumbnails=THUMBNAILS)
            add_manuals(catalog, {}, reviewed=_manual_matches(platform, catalog, reference, indexes.get("manuals.html")))
            soundtrack_review = reference.get("soundtracks", {})
            formats = ("vgm", "vgz", "kss", "mp3", "ogg", "flac") if platform == "virtualboy" else ("vgm", "vgz", "kss")
            catalog["summary"]["soundtracks"] = add_soundtracks(
                connection, catalog, platform=tuple(soundtrack_review.get("system", SYSTEMS[platform])),
                secondary_platform=None, formats=soundtrack_review.get("formats", formats),
                aliases=soundtrack_review.get("aliases", ()), reviewed_sources=soundtrack_review.get("sources"),
            )
            catalog["summary"]["metadata"] = retail.enrichment_coverage(catalog, markets=markets)
            if issues:
                catalog["summary"]["sourceWarnings"] = issues
            if publish_catalog:
                retail.publish(connection, catalog, platform)
    finally:
        engine.dispose()
    if report is not None:
        retail.write_report(report, catalog)
    return {"published": publish_catalog, **catalog["summary"]}
