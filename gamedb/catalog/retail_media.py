"""Resolve descriptions, artwork, and manuals for retail releases."""

from collections import defaultdict
import json
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import text

from gamedb.catalog.launchbox_media import IMAGE_KINDS, REGIONS as LAUNCHBOX_REGIONS
from gamedb.catalog.media import BAD_CHARS
from gamedb.catalog.cartridges import COUNTRY_MARKETS
from gamedb.catalog.references import GAMING_ALEXANDRIA, KIRKLAND_ITEM, PEEBS, PEEBS_ITEM, PEEBS_JP, THUMBNAILS
from gamedb.catalog.retail_source import known_credit
from gamedb.config import PROJECT_ROOT
from gamedb.launchbox.image_cache import valid_filename
from gamedb.launchbox.matching import match_candidates, title_key


LAUNCHBOX_PLATFORMS = {"Super Nintendo Entertainment System", "Nintendo Super Famicom", "Nintendo Sufami Turbo"}
LAUNCHBOX_GAME = "https://gamesdb.launchbox-app.com/games/details/"
LAUNCHBOX_IMAGE_CHECKSUMS = PROJECT_ROOT / "reference/launchbox_retail_image_checksums.json"
LIBRETRO_KINDS = {"Named_Boxarts": "boxart", "Named_Titles": "title", "Named_Snaps": "snap", "Named_Logos": "logo"}
MANUAL_NOTE = re.compile(r"\s*\(\s*(?:high quality|poor quality|color|manual scan)\s*\)\s*$", re.I)


def release_names(release):
    return {*release["titles"], *(archive["title"] for archive in release.get("archives", ()))}


def _manual_key(name):
    name = re.sub(r"(?<=\d)×(?=\d)", "x", name)
    key = title_key(name.replace("_", " ").replace("&", " and "))
    return "".join(key.split())


def _manual_regions(name):
    regions = {
        item.strip() for group in re.findall(r"\(([^()]*)\)", name)
        for item in group.split(",") if item.strip() in COUNTRY_MARKETS
    }
    return regions, {COUNTRY_MARKETS[region] for region in regions}


def _manual_name(name):
    name = MANUAL_NOTE.sub("", name)
    while match := re.search(r"\s*\(([^()]*)\)\s*$", name):
        if _manual_regions(match[0])[0] or re.fullmatch(r"Rev\s+\d+", match[1], flags=re.I):
            name = name[:match.start()].rstrip()
        else:
            break
    return name


def _archive_manuals(content, item):
    payload = json.loads(content)
    if payload.get("metadata", {}).get("identifier") != item:
        raise ValueError(f"Unexpected manual archive item {item}")
    for file in payload["files"]:
        name = file["name"]
        if file.get("source") != "original" or not name.lower().endswith(".pdf"):
            continue
        if re.search(r"\b(?:fan (?:translation|manual)|unl|peripheral|comic)\b", name, re.I):
            continue
        stem = name[:-4]
        regions, markets = _manual_regions(stem)
        if len(markets) != 1:
            continue
        yield _manual_name(stem), markets, {
            "name": stem, "regions": sorted(regions), "language": "Japanese" if markets == {"JP"} else None,
            "url": f"https://archive.org/download/{item}/{quote(name, safe='')}",
            "source": "Kirkland's Manual Labor" if item == KIRKLAND_ITEM else "Peebs’ SNES Manual Archive",
            "sourceUrl": PEEBS, "format": "PDF", "sha1": file.get("sha1"),
        }, 3 if item == KIRKLAND_ITEM else 2


def _archive_link(href):
    parsed = urlsplit(href)
    if parsed.hostname == "www.google.com" and parsed.path == "/url":
        href = parse_qs(parsed.query).get("q", [""])[0]
        parsed = urlsplit(href)
    if parsed.scheme == "https" and (
        parsed.hostname == "archive.org" or re.fullmatch(r"ia[0-9]+\.us\.archive\.org", parsed.hostname or "")
    ) and re.match(r"/(?:details|download|\d+/items)/", parsed.path):
        return href
    return None


def _manual_link_regions(path):
    parts = unquote(path).strip("/").split("/")
    label = parts[1] if parts[0] == "details" and len(parts) > 1 else parts[-1]
    explicit, _ = _manual_regions(label)
    if explicit:
        return sorted(explicit)
    slug = re.sub(r"\.(?:pdf|jpg|png)$", "", label, flags=re.I)
    words = re.findall(r"[A-Z0-9]+", slug.upper())
    while words and words[-1] in {"MANUAL", "HIRES", "SCANS", "SCAN", "TEXT", "PDF", "COLOR", "HQ"}:
        words.pop()
    countries = []
    while words and words[-1] in COUNTRY_MARKETS:
        countries.append(words.pop())
    return sorted(set(countries))


def _sheet_manuals(content, japanese):
    soup = BeautifulSoup(content, "html.parser")
    for row in soup.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        name = cells[0].get_text(" ", strip=True)
        if not name or re.search(r"\b(?:fan manual|fan translation|prototype|comic)\b", name, re.I):
            continue
        for link in cells[1].select("a[href]"):
            href = _archive_link(link["href"])
            if not href:
                continue
            path = urlsplit(href).path
            country = _manual_link_regions(path)
            markets = {"JP"} if japanese else {COUNTRY_MARKETS[region] for region in country}
            if len(markets) != 1:
                continue
            yield _manual_name(name), markets, {
                "name": name, "regions": ["JPN"] if japanese else country, "language": "Japanese" if japanese else None,
                "url": href, "source": "Peebs’ Super Famicom Manuals" if japanese else "Peebs’ SNES Manual Archive",
                "sourceUrl": PEEBS_JP if japanese else PEEBS,
                "format": "PDF" if path.lower().endswith(".pdf") else "Scan",
            }, 1


def _gaming_alexandria_manuals(content, source):
    payload = json.loads(content)
    if payload.get("url") != source:
        raise ValueError("Unexpected Super Famicom manual index")
    for item in payload["records"]:
        for url in item.get("manual", ()):
            location = urlsplit(url)
            if (location.scheme == "https" and location.hostname == "www.gamingalexandria.com"
                    and location.path.startswith(("/highquality/sfc/", "/highquality/snes/"))
                    and unquote(location.path).endswith(" - Manual.pdf")):
                yield item["title"], {"JP"}, {
                    "name": item["title"], "regions": ["JPN"], "language": "Japanese", "format": "PDF",
                    "url": url, "source": "Gaming Alexandria", "sourceUrl": item["sourceUrl"],
                }, 0


def add_manuals(catalog, indexes, aliases=(), reviewed=()):
    releases = {release["key"]: release for game in catalog["games"] for release in game["releases"]
                if release["status"] == "matched"}
    lookup = defaultdict(set)
    for key, release in releases.items():
        for name in release_names(release):
            lookup[release["market"], _manual_key(name)].add(key)
    by_edition = {(release["edition"], release["market"]): release["key"] for release in releases.values()}
    for alias in aliases:
        key = by_edition.get((alias["edition"], alias["market"]))
        if key:
            lookup[alias["market"], _manual_key(alias["title"])].add(key)

    choices = defaultdict(list)
    sources = [
        ("kirkland-archive.json", _archive_manuals, KIRKLAND_ITEM),
        ("peebs-archive.json", _archive_manuals, PEEBS_ITEM),
        ("peebs-rows-en.html", _sheet_manuals, False),
        ("peebs-rows-jp.html", _sheet_manuals, True),
        ("ga-sfc-references.json", _gaming_alexandria_manuals, GAMING_ALEXANDRIA),
    ]
    for filename, reader, edition in sources:
        if filename not in indexes:
            continue
        for title, markets, manual, rank in reader(indexes[filename].content, edition):
            for market in markets:
                matches = lookup[market, _manual_key(title)]
                if len(matches) == 1:
                    (key,) = matches
                    choices[key].append((rank, manual))
    for key, candidates in choices.items():
        selected = {}
        for _, manual in sorted(candidates, key=lambda item: (-item[0], item[1]["name"], item[1]["url"])):
            countries = tuple(sorted({{"USA": "US", "Japan": "JPN", "JP": "JPN", "EU": "PAL",
                                       "EUR": "PAL", "Europe": "PAL"}.get(r, r) for r in manual["regions"]}))
            variant = re.search(r"\(Rev\s+\d+\)", manual["name"], flags=re.I)
            selected.setdefault((countries, variant[0].casefold() if variant else ""), manual)
        releases[key]["manuals"] = list({manual["url"]: manual for manual in selected.values()}.values())
    for record in reviewed:
        if key := by_edition.get((record["edition"], record["market"])):
            release = releases[key]
            manual = {field: value for field, value in record.items() if field not in {"edition", "market"}}
            scans = release.setdefault("manuals", [])
            if not any(scan["url"] == manual["url"] for scan in scans):
                scans.append(manual)


LAUNCHBOX_GAMES_SQL = text("""
    SELECT record.database_id, record.record_type, record.raw_record
    FROM staging.launchbox_record record
    JOIN (
        SELECT database_id FROM staging.launchbox_record
        WHERE import_id = :snapshot AND record_type = 'Game'
          AND raw_record->>'Platform' = ANY(CAST(:platforms AS text[]))
    ) games USING (database_id)
    WHERE record.import_id = :snapshot AND record.record_type IN ('Game', 'GameAlternateName')
""")

LAUNCHBOX_LINKS_SQL = text("""
    SELECT DISTINCT fact.software_id, (evidence.match_details->>'database_id')::bigint AS database_id
    FROM catalog.software_fact fact
    JOIN catalog.software_fact_evidence evidence ON evidence.software_fact_id = fact.id
    WHERE fact.source_provider = 'launchbox' AND evidence.source_file_id = :snapshot
      AND fact.software_id = ANY(CAST(:software AS bigint[]))
      AND evidence.match_details->>'database_id' IS NOT NULL
""")

LAUNCHBOX_IMAGES_SQL = text("""
    SELECT image.database_id, image.file_name, image.image_type, image.region,
           nullif(image.raw_record->>'CRC32', '')::bigint AS crc32
    FROM staging.launchbox_image image
    JOIN staging.launchbox_image_import imported ON imported.import_id = image.import_id
    WHERE image.import_id = :snapshot AND image.database_id = ANY(CAST(:games AS bigint[]))
      AND image.image_type = ANY(CAST(:kinds AS text[]))
      AND (image.region <> '' OR image.image_type = 'Clear Logo')
      AND lower(left(image.file_name, 3)) <> 'r2_'
    ORDER BY image.database_id, image.region, image.file_name
""")


def _owners(catalog):
    owners = defaultdict(set)
    for game in catalog["games"]:
        for release in game["releases"]:
            for archive in release.get("archives", ()):
                owners[archive["softwareId"]].add(game["key"])
    return owners


def _scope_launchbox(connection, catalog, reviewed, *, platforms=LAUNCHBOX_PLATFORMS):
    names = connection.execute(text("""
        SELECT to_regclass('staging.launchbox_import') IS NOT NULL
           AND to_regclass('staging.launchbox_record') IS NOT NULL
    """)).scalar_one()
    if not names:
        return {}, {}
    snapshot = connection.execute(text("""
        SELECT id, source_revision FROM staging.launchbox_import ORDER BY imported_at DESC, id DESC LIMIT 1
    """)).one_or_none()
    if not snapshot:
        return {}, {}
    games, aliases = {}, defaultdict(set)
    parameters = {"snapshot": snapshot.id, "platforms": sorted(platforms)}
    for row in connection.execute(LAUNCHBOX_GAMES_SQL, parameters):
        if row.record_type == "Game":
            games[row.database_id] = row.raw_record
        elif name := row.raw_record.get("AlternateName"):
            aliases[row.database_id].add(name)

    owners = _owners(catalog)
    attributed = defaultdict(set)
    if connection.execute(text("SELECT to_regclass('catalog.software_fact_evidence') IS NOT NULL")).scalar_one():
        for row in connection.execute(LAUNCHBOX_LINKS_SQL, {"snapshot": snapshot.id, "software": sorted(owners)}):
            if len(owners[row.software_id]) == 1 and row.database_id in games:
                attributed[row.software_id].add(row.database_id)

    # Use each curated title once so same-name games compete for a source record.
    items = [dict(
        id=game["key"], manufacturer_name="", system_name="retail",
        titles={game["title"], *(name for release in game["releases"] for name in release_names(release))},
        match_facts={
            "release_date": {match[0] for release in game["releases"]
                             if (match := re.search(r"\b\d{4}\b", release["date"]))},
            "publisher": {game["publisher"]}, "developer": {game["developer"]},
        },
    ) for game in catalog["games"]]
    mappings = {("", "retail"): platforms}
    canonical = {row["software_id"]: row["selected_database_id"]
                 for row in match_candidates(items, games, aliases, mappings)}
    chosen = set()
    release_ids = {}
    for game in catalog["games"]:
        known = set()
        for release in game["releases"]:
            local = {item for archive in release.get("archives", ()) for item in attributed[archive["softwareId"]]}
            release_ids[release["key"]] = local
            known.update(local)
        direct = canonical.get(game["key"])
        if direct:
            known.add(direct)
        review = reviewed.get(game["title"], {})
        description_id = review.get("descriptionId")
        if description_id in games:
            direct = description_id
            known.add(description_id)
        with_overviews = {key for key in known if games[key].get("Overview", "").strip()}
        preferred = direct if direct in with_overviews else next(iter(with_overviews)) if len(with_overviews) == 1 else None
        if preferred:
            record = games[preferred]
            source = {"name": "LaunchBox", "url": f"{LAUNCHBOX_GAME}{preferred}",
                      "revision": snapshot.source_revision}
            game["description"] = {
                "text": record["Overview"].strip(),
                "source": source,
            }
            for field in ("developer", "publisher"):
                value = record.get(field.title())
                if not known_credit(game[field]) and known_credit(value):
                    game[field] = value
                    game.setdefault("creditSources", {})[field] = source
        market_ids, edition_ids = review.get("marketIds", {}), review.get("editionIds", {})
        for release in game["releases"]:
            keys = release_ids[release["key"]]
            reviewed_id = edition_ids.get(release["edition"], market_ids.get(release["market"]))
            if reviewed_id in games:
                release_ids[release["key"]] = keys = {reviewed_id}
            elif not keys and len(known) == 1:
                keys.update(known)
            chosen.update(keys)
    images = defaultdict(list)
    available = connection.execute(text("""
        SELECT to_regclass('staging.launchbox_image') IS NOT NULL
           AND to_regclass('staging.launchbox_image_import') IS NOT NULL
    """)).scalar_one()
    if available and chosen:
        parameters = {"snapshot": snapshot.id, "games": sorted(chosen), "kinds": sorted(IMAGE_KINDS)}
        for row in connection.execute(LAUNCHBOX_IMAGES_SQL, parameters):
            if valid_filename(row.file_name):
                images[row.database_id].append((row, games[row.database_id]["Name"]))
    return release_ids, images


def _libretro_paths(indexes, thumbnails=THUMBNAILS):
    paths = {}
    for name, (folder, revision) in thumbnails.items():
        filename = f"thumbs-{name}.json"
        if filename not in indexes:
            continue
        tree = json.loads(indexes[filename].content)
        if tree.get("truncated") or tree["sha"] != revision:
            raise ValueError(f"Unexpected Libretro image index for {folder}")
        paths[name] = {row["path"] for row in tree["tree"]
                       if row["type"] == "blob" and row["mode"] in {"100644", "100755"}}
    return paths


def _libretro_art(release, paths, reviewed=(), *,
                  thumbnails=THUMBNAILS, thumbnail_key="snes", country_markets=COUNTRY_MARKETS):
    folder_key = "sufami" if release["channel"] == "sufami-turbo" else thumbnail_key
    folder, revision = thumbnails[folder_key]
    repository = folder.replace(" ", "_")
    local_titles = {title_key(title) for title in release["titles"]}
    for archive in release.get("archives", ()):
        regions = archive["regions"]
        markets = {country_markets[region] for region in regions if region in country_markets}
        exclusive = markets == {release["market"]} and "WORLD" not in regions
        for name in archive["archiveNames"]:
            stem = PurePosixPath(name).stem.translate(BAD_CHARS)
            for directory, kind in LIBRETRO_KINDS.items():
                review = reviewed.get((name, kind)) if reviewed else None
                if review and review["market"] != release["market"]:
                    continue
                if kind == "boxart" and not (exclusive or review):
                    continue
                if kind == "logo" and not (exclusive or review or title_key(archive.get("title", "")) in local_titles):
                    continue
                filename = (review or {}).get("filename", f"{stem}.png")
                path = f"{directory}/{filename}"
                if path in paths.get(folder_key, ()):
                    rank = 2 if exclusive else 0
                    if not archive["revisions"] and not archive["versions"]:
                        rank += 1
                    source = f"https://github.com/libretro-thumbnails/{repository}"
                    asset = {
                        "url": f"https://raw.githubusercontent.com/libretro-thumbnails/{repository}/{revision}/{quote(path)}",
                        "source": {"name": "Libretro", "url": source, "revision": revision},
                        "regions": regions, "basis": "archive" if exclusive else "shared-rom",
                        "archive": name,
                    }
                    if review:
                        asset.update(regions=review["regions"], basis="reviewed-image", evidence=review["source"])
                    yield 4 if review else rank, kind, asset


def _launchbox_art(release, keys, images, *, country_markets=COUNTRY_MARKETS, checksum_reviews=None):
    local_titles = {title_key(title) for title in release["titles"]}
    for key in keys:
        for image, title in images.get(key, ()):
            kind = IMAGE_KINDS[image.image_type]
            regions = sorted(LAUNCHBOX_REGIONS.get(image.region, ()))
            regional = {country_markets.get(region) for region in regions} == {release["market"]}
            if not regional and not (kind == "logo" and image.region in ("", "World")
                                     and title_key(title) in local_titles):
                continue
            path = f"launchbox/{kind}/{image.file_name}"
            crc32 = (checksum_reviews or {}).get((image.file_name, image.crc32), image.crc32)
            yield (2 if regional else -1), kind, {
                "url": f"/media/{path}", "preview": f"/previews/320/{path}", "path": path,
                "filename": image.file_name, "crc32": crc32, "regions": regions,
                "basis": "source-region" if regional else "source-title",
                "source": {"name": "LaunchBox", "url": f"{LAUNCHBOX_GAME}{key}"},
            }


def add_descriptions_and_art(connection, catalog, indexes, reference, *,
                             platforms=LAUNCHBOX_PLATFORMS, thumbnails=THUMBNAILS,
                             thumbnail_key="snes", country_markets=COUNTRY_MARKETS):
    reviewed = reference.get("metadata", {})
    unavailable = set(reference.get("unavailableImages", ()))
    artwork_regions = {(record["archiveName"], record["kind"]): record
                       for record in reference.get("artworkRegions", ())}
    checksum_reviews = {(filename, review["previousCrc32"]): review["crc32"]
                        for filename, review in json.loads(LAUNCHBOX_IMAGE_CHECKSUMS.read_text(encoding="utf-8")).items()}
    release_ids, images = _scope_launchbox(connection, catalog, reviewed, platforms=platforms)
    paths = _libretro_paths(indexes, thumbnails)
    for game in catalog["games"]:
        if description := reviewed.get(game["title"], {}).get("description"):
            game["description"] = description
        for field in ("developer", "publisher"):
            if not known_credit(game[field]):
                credits = {release[field]: release["creditSources"][field] for release in game["releases"]
                           if known_credit(release.get(field))}
                if len(credits) == 1:
                    value, source = next(iter(credits.items()))
                    game[field] = value
                    game.setdefault("creditSources", {})[field] = source
        for release in game["releases"]:
            if release["status"] != "matched":
                continue
            art = {}
            candidates = (*_libretro_art(release, paths, artwork_regions, thumbnails=thumbnails,
                                        thumbnail_key=thumbnail_key, country_markets=country_markets), *_launchbox_art(
                release, release_ids.get(release["key"], ()), images,
                country_markets=country_markets, checksum_reviews=checksum_reviews,
            ))
            for _, kind, asset in sorted(candidates, key=lambda item: (-item[0], item[2]["url"])):
                if asset.get("filename") not in unavailable:
                    art.setdefault(kind, asset)
            if art:
                release["artwork"] = art
