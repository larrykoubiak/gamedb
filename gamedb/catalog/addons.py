"""Build add-on releases separately, then attach them to their home catalogs."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import PurePosixPath

from gamedb.catalog import retail
from gamedb.catalog.cartridges import VERIFIED_ROM_SQL
from gamedb.catalog.disc_catalog import DISC_SYSTEMS, addon_disc_archives, approved_disc_matches
from gamedb.catalog.megadrive_media import add_scans, sega_retro_scans
from gamedb.catalog.references import read_index
from gamedb.catalog.retail_media import add_descriptions_and_art
from gamedb.catalog.soundtracks import add_soundtracks
from gamedb.config import PROJECT_ROOT


@dataclass(frozen=True)
class Addon:
    key: str
    system: tuple[str, str]
    launchbox: str
    thumbnails: tuple[str, str]
    formats: tuple[str, ...]
    medium: str
    channel: str = "cartridge"


ADDONS = {
    "mastersystem": Addon(
        "sg1000", ("Sega", "SG-1000"), "Sega SG-1000",
        ("Sega - SG-1000", "3a0e96504581c36cbb8a0d6860099565142ef7fd"),
        ("vgm", "vgz", "kss", "sgc"), "SG-1000 cartridge",
    ),
    "nes": Addon(
        "fds", ("Nintendo", "Famicom Disk System"), "Nintendo Famicom Disk System",
        ("Nintendo - Family Computer Disk System", "09337470d081504faee7b0b6bcee0bdf8182c292"),
        ("nsf", "nsfe", "vgm", "vgz"), "Famicom Disk Card", "disk",
    ),
    "megadrive": Addon(
        "32x", ("Sega", "32X"), "Sega 32X",
        ("Sega - 32X", "198130ac14ff7ba9568a7db01a0f7df68fc5bf95"),
        ("vgm", "vgz", "gym"), "32X cartridge",
    ),
    "pcengine": Addon(
        "supergrafx", ("NEC", "SuperGrafx"), "PC Engine SuperGrafx",
        ("NEC - PC Engine SuperGrafx", "3be96b504b32eecd94e2c3c0d7fcd6dfc8eaf9c3"),
        ("hes", "vgm", "vgz"), "SuperGrafx HuCard",
    ),
}
DISC_ADDONS = {
    "megadrive": Addon(
        "segacd", DISC_SYSTEMS["segacd"], "Sega CD",
        ("Sega - Mega-CD - Sega CD", "8a44ee306e92f800b1f05e2f9808d90e752a5338"),
        ("vgm", "vgz", "flac", "mp3", "wav"), "Sega CD", "optical-disc",
    ),
    "pcengine": Addon(
        "pcecd", DISC_SYSTEMS["pcecd"], "NEC TurboGrafx-CD",
        ("NEC - PC Engine CD - TurboGrafx-CD", "341caf6e4bd096586edec34a2cab593c9ba2f3b5"),
        ("hes", "vgm", "vgz", "flac", "mp3", "wav"), "CD-ROM²", "optical-disc",
    ),
    "neogeo": Addon(
        "neogeocd", DISC_SYSTEMS["neogeocd"], "SNK Neo Geo CD",
        ("SNK - Neo Geo CD", "d583692e45d279566b87ee60d6a93936326dd964"),
        ("vgm", "vgz", "flac", "mp3", "wav"), "Neo Geo CD", "optical-disc",
    ),
}
SEGA_32X_SCANS = {
    **{f"32X {country} manual scans": ("manual", country) for country in ("JP", "US", "EU", "BR")},
    **{f"32X {country} box scans": ("boxart", country) for country in ("JP", "US", "EU", "BR")},
}


def _key(hardware, *parts):
    return sha256("\x00".join(("gamedb:addon-retail", hardware, *parts)).encode()).hexdigest()[:32]


def _addon_catalog(addon, reference):
    source = reference["source"]
    games, archive_aliases, parents = {}, [], {}
    for row in reference["titles"]:
        edition = row["title"]
        title = row.get("gameTitle", edition)
        game = games.setdefault(title, {
            "key": _key(addon.key, "game", title), "title": title, "aliases": [],
            "developer": row["developer"], "publisher": row["publisher"], "releases": [],
        })
        if parent := row.get("parentTitle"):
            if parents.setdefault(title, parent) != parent:
                raise ValueError(f"Conflicting parent titles for {title!r}")
        for name in row.get("aliases", ()):
            alias = {"title": name, "regions": []}
            if alias not in game["aliases"]:
                game["aliases"].append(alias)
        credits = {field: row[field] for field in ("developer", "publisher") if row[field]}
        for market, date in row["dates"].items():
            local = row.get("regionalTitles", {}).get(market, edition)
            key = _key(addon.key, "release", edition, market)
            if any(release["key"] == key for release in game["releases"]):
                raise ValueError(f"Duplicate {addon.key} edition {edition!r} in {market}")
            release = {
                "key": key, "edition": edition, "market": market, "titles": [local],
                "date": date, "hardware": row.get("hardware", addon.key), "source": source,
                "medium": row.get("medium", addon.medium), "channel": row.get("channel", addon.channel),
                **credits, "creditSources": dict.fromkeys(credits, source),
            }
            if product_codes := row.get("productCodes"):
                release["productCodes"] = product_codes
            if required := row.get("requiredHardware"):
                release["requiredHardware"] = required
            game["releases"].append(release)
            if local != title:
                alias = {"title": local, "regions": [market]}
                if alias not in game["aliases"]:
                    game["aliases"].append(alias)
            archive_aliases.extend(
                {"edition": edition, "market": market, "archiveTitle": name, "evidence": source["url"]}
                for name in row.get("archiveTitles", ()) if retail._title_key(name) != retail._title_key(local)
            )
    return {"source": source, "games": list(games.values())}, archive_aliases, parents


def _fds_archives(connection, archives):
    # Quick Disk and FDS images have the same archive labels. Keep the verified
    # FDS-format release, which is also the base used by the catalog's patches.
    roms = connection.execute(VERIFIED_ROM_SQL, {"signatures": [archive["signature"] for archive in archives]})
    signatures = {rom.signature for rom in roms if PurePosixPath(rom.member_path).suffix.casefold() == ".fds"}
    return [dict(archive, channel="disk") for archive in archives if archive["signature"] in signatures]


def _merge_games(catalog, addon_catalog, parents):
    home_games = {game["title"]: game for game in catalog["games"]}
    for extra in addon_catalog["games"]:
        if extra["title"] not in parents:
            catalog["games"].append(extra)
            continue
        parent_title = parents[extra["title"]]
        if parent_title not in home_games:
            raise ValueError(f"Missing parent title {parent_title!r} for {extra['title']!r}")
        game = home_games[parent_title]
        aliases = [{"title": extra["title"], "regions": []}, *extra["aliases"]]
        game["aliases"].extend(alias for alias in aliases
                               if alias["title"] != game["title"] and alias not in game["aliases"])
        game["releases"].extend(extra["releases"])
        if description := extra.get("description"):
            for release in extra["releases"]:
                release["description"] = description
        if extra.get("soundtrackLinks"):
            game.setdefault("soundtrackLinks", []).extend(extra["soundtrackLinks"])
    catalog["games"].sort(key=lambda game: game["title"].casefold())


def _add_manuals(catalog, reference):
    releases = {(release["edition"], release["market"]): release
                for game in catalog["games"] for release in game["releases"]}
    for entry in reference.get("manuals", ()):
        release = releases[entry["edition"], entry["market"]]
        manual = {key: value for key, value in entry.items() if key not in ("edition", "market")}
        existing = release.setdefault("manuals", [])
        if manual.get("localArchive"):
            # Prefer an available local PDF over a second scan of the same regional booklet.
            existing[:] = [item for item in existing if item.get("regions") != manual["regions"]]
        existing.append(manual)


def add_retail_addon(connection, catalog, directory, addon, markets):
    path = PROJECT_ROOT / "reference" / f"{addon.key}_retail.json"
    reference = json.loads(path.read_text(encoding="utf-8"))
    additions, aliases, parents = _addon_catalog(addon, reference)
    if addon.channel == "optical-disc":
        archives = list(addon_disc_archives(connection, addon.key, markets, reference))
        verified = list(approved_disc_matches(archives, reference.get("verifiedArchives", ())))
    else:
        verified = reference.get("verifiedArchives", ())
        archives = retail.read_archives(connection, *addon.system, verified)
        if addon.key == "fds":
            archives = _fds_archives(connection, archives)
    retail.match_archives(additions, archives, aliases, verified, markets=markets)
    if included := reference.get("includedIn"):
        games = {game["title"]: game for game in additions["games"]}
        home = {game["title"]: game for game in catalog["games"]}
        releases = {(release["edition"], release["market"]): release
                    for game in additions["games"] for release in game["releases"]}
        for item in included:
            release = releases[item["edition"], item["market"]]
            compilation = games[item["compilation"]]
            sibling = next((sibling for sibling in compilation["releases"] if
                sibling["status"] == "matched" and sibling["market"] == item["market"]
            ), None)
            if release["status"] == "unmatched" and sibling:
                target = home[parents[compilation["title"]]] if compilation["title"] in parents else compilation
                release.update(status="matched", archives=[],
                               includedIn={"key": target["key"], "title": compilation["title"], "release": sibling["key"]})
        retail.summarize_matches(additions, len(archives), markets)

    folder, revision = addon.thumbnails
    repo = folder.replace(" ", "_")
    index_name = f"thumbs-{addon.key}.json"
    index = read_index(directory / index_name,
                       f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/{revision}?recursive=1")
    add_descriptions_and_art(
        connection, additions, {index_name: index}, reference, platforms={addon.launchbox},
        thumbnails={addon.key: addon.thumbnails}, thumbnail_key=addon.key,
    )
    sources = [index]
    warnings = []
    if addon.key == "32x":
        scans = sega_retro_scans(directory, SEGA_32X_SCANS)
        add_scans(additions, scans, aliases=aliases, scan_categories=SEGA_32X_SCANS)
        sources.extend(source for _, _, indexes, _ in scans for source in indexes)
        warnings.extend(error for _, _, _, error in scans if error)
    _add_manuals(additions, reference)
    addon_summary = additions["summary"]
    addon_summary["metadata"] = retail.enrichment_coverage(additions, markets)
    addon_summary["soundtracks"] = add_soundtracks(
        connection, additions, platform=addon.system, secondary_platform=None, formats=addon.formats,
        aliases=[{"edition": item["edition"], "title": item["archiveTitle"]} for item in aliases],
    )
    base_summary = catalog["summary"]
    base_count = len(catalog["games"])
    _merge_games(catalog, additions, parents)
    catalog.setdefault("addonSources", {})[addon.key] = additions["source"]
    catalog["enrichmentSources"].extend({"url": source.url, "sha256": source.digest} for source in sources)
    retail.summarize_matches(catalog, base_summary.get("eligibleArchives", 0) + len(archives), markets)
    summary = catalog["summary"]
    for market, counts in base_summary["byMarket"].items():
        summary["byMarket"][market].update({key: value for key, value in counts.items()
                                            if key not in summary["byMarket"][market]})
    summary["metadata"] = retail.enrichment_coverage(catalog, markets)
    base_metadata = base_summary.get("metadata", {})
    if "romHeader" in base_metadata.get("releases", {}):
        summary["metadata"]["releases"]["romHeader"] = base_metadata["releases"]["romHeader"]
        for market, counts in base_metadata["byMarket"].items():
            if "romHeader" in counts:
                summary["metadata"]["byMarket"][market]["romHeader"] = counts["romHeader"]
    if "mediaTitles" in base_summary:
        summary["mediaTitles"] = {
            field: sum(any(release.get(field) for release in game["releases"]) for game in catalog["games"])
            for field in base_summary["mediaTitles"]
        }
    summary["soundtracks"] = {
        "titles": sum(bool(game.get("soundtrackLinks")) for game in catalog["games"]),
        "sets": sum(len(game.get("soundtrackLinks", ())) for game in catalog["games"]),
    }
    warnings = [*base_summary.get("sourceWarnings", ()), *warnings]
    if warnings:
        summary["sourceWarnings"] = warnings
    summary["addons"] = {
        **base_summary.get("addons", {}),
        addon.key: {**addon_summary, "sharedTitles": base_count + len(additions["games"]) - summary["games"]},
    }
