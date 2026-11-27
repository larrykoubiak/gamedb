"""Fill handheld artwork gaps from the mounted library and reviewed sources."""

from collections import defaultdict
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, unquote, urlsplit

from sqlalchemy import text

from gamedb.config import PROJECT_ROOT, ProjectEnvironment
from gamedb.database import create_database_engine

from . import retail
from .handheld_media import THUMBNAILS
from .handhelds import (
    COUNTRIES, DEVELOPMENT, REFERENCE as RETAIL_REFERENCE, SUFFIX, _names, _strip_regions,
    apply_handheld_retail_review,
)
from .media import BAD_CHARS, IMAGE_EXTENSIONS, KINDS


PLATFORMS = (*retail.HANDHELD_PLATFORMS, "virtualboy")
REFERENCE = PROJECT_ROOT / "reference/handheld_artwork.json"
FOLDERS = {
    **{platform: folder for platform, (folder, _) in THUMBNAILS.items()},
    "gamemaster": "Hartung - Game Master",
    "gp32": "GamePark - GP32",
    "virtualboy": "Nintendo - Virtual Boy",
}
THUMBNAIL_TAG = re.compile(
    r"rev(?:ision)? [a-z0-9.]+|v\d[\w.]*|(?:en|ja|fr|de|es|it|nl|pt|sv|no|da|fi|ko|zh|ru)"
    r"(?:,(?:en|ja|fr|de|es|it|nl|pt|sv|no|da|fi|ko|zh|ru))*", re.I,
)
ARTWORK_FIELDS = {"boxart": "boxart", "title": "titleScreen", "snap": "gameplay", "logo": "logo"}
SUPPLEMENT_ROOT = PurePosixPath("catalog/handheld-artwork")


def artwork_sources():
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def thumbnail_root():
    return Path(os.environ.get("GAMEDB_LIBRETRO_THUMBNAILS") or PROJECT_ROOT / "data/libretro-thumbnails")


def _name_keys(names):
    return {retail._title_key(name.translate(BAD_CHARS)) for value in names for name in _names(value)}


def _thumbnail_identity(stem):
    while match := SUFFIX.search(stem):
        name, regions = _strip_regions(stem)
        if regions:
            return name, regions
        if not THUMBNAIL_TAG.fullmatch(match[1]):
            break
        stem = stem[:match.start()]
    return stem, []


def _local_urls(relative_path):
    path = quote(relative_path)
    return {"url": f"/media/{path}", "preview": f"/previews/320/{path}"}


def _mirror_libretro(asset, folder, root):
    if not folder or asset.get("source", {}).get("name") != "Libretro":
        return False
    remote = urlsplit(asset["url"])
    parts = PurePosixPath(unquote(remote.path)).parts
    if (remote.hostname != "raw.githubusercontent.com" or len(parts) != 6
            or parts[1:3] != ("libretro-thumbnails", folder.replace(" ", "_"))
            or parts[4] not in KINDS or PurePosixPath(parts[5]).suffix.lower() not in IMAGE_EXTENSIONS):
        return False
    relative = PurePosixPath(folder, *parts[4:]).as_posix()
    if not (root / relative).is_file():
        return False
    asset.update(_local_urls(relative), fallbackUrl=asset["url"])
    return True


def _local_thumbnails(games, folder, root):
    if not folder:
        return {}
    owners = defaultdict(set)
    for game in games:
        names = {game["title"], *(item["title"] for item in game.get("aliases", ())),
                 *(title for release in game["releases"] for title in release["titles"])}
        for title in _name_keys(names):
            owners[title].add(game["key"])
    thumbnails = defaultdict(list)
    for directory, (kind, quality) in KINDS.items():
        for path in (root / folder / directory).glob("*"):
            if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file() or DEVELOPMENT.search(path.stem):
                continue
            name, regions = _thumbnail_identity(path.stem)
            matches = {game for title in _name_keys([name]) for game in owners[title]}
            if len(matches) != 1:
                continue
            relative = path.relative_to(root).as_posix()
            asset = {
                **_local_urls(relative),
                "source": {"name": "Libretro", "url": "https://github.com/libretro/libretro-thumbnails",
                           "record": relative},
                "regions": regions, "basis": "mounted-thumbnail",
            }
            thumbnails[next(iter(matches))].append((kind, quality, asset))
    return thumbnails


def _fill_thumbnails(art, candidates, market):
    ranked = []
    for kind, quality, asset in candidates:
        regions = asset["regions"]
        markets = {COUNTRIES[region] for region in regions}
        if market in markets:
            rank = 3 if markets == {market} else 2
        elif not markets or markets == {"WORLD"} or market == "UNK":
            rank = 1
        else:
            continue
        ranked.append((rank, quality, kind, asset))
    for _, _, kind, asset in sorted(ranked, key=lambda item: (-item[0], item[1], item[3]["url"])):
        art.setdefault(kind, asset)


def _product_codes(release):
    return {code.replace("-", "").upper() for code in release.get("productCodes", ())}


def _product_code_owners(games):
    owners = defaultdict(set)
    for game in games:
        for release in game["releases"]:
            for code in _product_codes(release):
                owners[code].add(game["key"])
    return owners


def _add_product_code_art(art, release, unique_codes, sources, root):
    for entry in sources:
        codes = sorted(_product_codes(release) & unique_codes & entry["files"].keys())
        for code in codes:
            for kind, path in entry["files"][code].items():
                if kind in art:
                    continue
                url = entry["baseUrl"] + quote(path)
                asset = {
                    "url": url,
                    "source": {**entry["source"], "record": code},
                    "basis": "product-code",
                    "label": entry["labels"][kind],
                }
                relative = (SUPPLEMENT_ROOT / entry["localDirectory"] / path).as_posix()
                if (root / relative).is_file():
                    asset.update(_local_urls(relative), fallbackUrl=url)
                art[kind] = asset


def _coverage(games):
    cover = sum(any("boxart" in release.get("artwork", {}) for release in game["releases"]) for game in games)
    illustrated = sum(any(release.get("artwork") for release in game["releases"]) for game in games)
    assets = sum(len(release.get("artwork", {})) for game in games for release in game["releases"])
    return {"covers": cover, "illustrated": illustrated, "releaseImages": assets}


def fill_handheld_artwork(catalog, platform, root, reference):
    """Supplement existing matches while preserving release and download identity."""
    games = catalog["games"]
    folder = FOLDERS.get(platform)
    thumbnails = _local_thumbnails(games, folder, root)
    explicit = {item["release"]: item for item in reference.get("releases", ())}
    sources = reference.get("productCodeSources", ())
    unique_codes = {code for code, owners in _product_code_owners(games).items() if len(owners) == 1} if sources else set()
    before = _coverage(games)
    mirrored = 0
    for game in games:
        for release in game["releases"]:
            art = release.get("artwork", {}).copy()
            for kind, asset in art.items():
                asset = asset.copy()
                mirrored += _mirror_libretro(asset, folder, root)
                art[kind] = asset
            if record := explicit.get(release["key"]):
                signature = record.get("archiveSignature")
                archive_matches = not signature or any(
                    archive.get("signature") == signature for archive in release.get("archives", ())
                )
                if archive_matches and (record["title"], record["market"]) == (game["title"], release["market"]):
                    for kind, asset in record["images"].items():
                        url = asset["url"]
                        if url.startswith("/media/") and not (root / unquote(url.removeprefix("/media/"))).is_file():
                            continue
                        art.setdefault(kind, asset)
            _add_product_code_art(art, release, unique_codes, sources, root)
            _fill_thumbnails(art, thumbnails.get(game["key"], ()), release["market"])
            if art:
                release["artwork"] = art
    after = _coverage(games)
    summary = catalog["summary"]
    summary.setdefault("mediaTitles", {})["artwork"] = after["illustrated"]
    if "metadata" in summary:
        by_market = summary["metadata"]["byMarket"]
        for counts in by_market.values():
            counts.update(dict.fromkeys(ARTWORK_FIELDS.values(), 0))
        for game in games:
            for release in game["releases"]:
                counts = by_market[release["market"]]
                for kind in release.get("artwork", {}).keys() & ARTWORK_FIELDS.keys():
                    counts[ARTWORK_FIELDS[kind]] += 1
        for field in ARTWORK_FIELDS.values():
            summary["metadata"]["releases"][field] = sum(counts[field] for counts in by_market.values())
    return {"before": before, "after": after, "mirrored": mirrored}


def refresh_handheld_artwork(platforms, *, publish=False, report=None):
    ProjectEnvironment().load()
    root = thumbnail_root()
    reference = artwork_sources()
    curation = json.loads(RETAIL_REFERENCE.read_text(encoding="utf-8"))
    engine = create_database_engine()
    results = {}
    try:
        for platform in platforms:
            table = retail.retail_tables(platform)[0]
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
                if publish:
                    connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:catalog))"),
                                       {"catalog": f"gamedb.{platform}-retail"})
                else:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                exists = connection.execute(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": table}).scalar_one()
                if not exists:
                    results[platform] = {"skipped": "No published catalog"}
                    continue
                catalog = connection.exec_driver_sql(f"SELECT payload FROM {table} WHERE singleton").scalar_one()
                removed = apply_handheld_retail_review(catalog, curation.get(platform, {}))
                results[platform] = result = fill_handheld_artwork(catalog, platform, root, reference.get(platform, {}))
                result["retailReview"] = removed
                if publish and (removed or result["mirrored"] or result["before"] != result["after"]):
                    retail.publish(connection, catalog, platform)
                if report:
                    retail.write_report(report / f"{platform}.json", catalog)
    finally:
        engine.dispose()
    return {"published": publish, "platforms": results}
