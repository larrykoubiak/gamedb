"""Associate US PlayStation manuals and reviewed cover scans with the retail checklist."""

from collections import defaultdict
import json
from pathlib import PurePosixPath
import re
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup

from .references import read_index
from .retail import _compact_title


KIRKLAND = "https://www.videogamemanual.com/ps1/"
ARCHIVE_ITEM = "SonyPlaystationManuals"
ARCHIVE = f"https://archive.org/details/{ARCHIVE_ITEM}"
MANUAL_NAME = re.compile(r"(.+?)(?: \((LB|GH|CE|FE)\))? \(USA\)\.pdf", re.I)


def _kirkland_asset(filename, **checksum):
    return {"url": KIRKLAND + quote(filename), "source": "Kirkland’s Manual Labor",
            "sourceUrl": KIRKLAND + "index.html", **checksum}


def _catalogue_manuals(content):
    page = BeautifulSoup(content, "html.parser")
    for link in page.select("a[href]"):
        url = urlsplit(link["href"])
        if url.scheme != "https" or url.hostname != "www.videogamemanual.com":
            continue
        path = PurePosixPath(unquote(url.path))
        if path.parent.as_posix() == "/ps1" and (match := MANUAL_NAME.fullmatch(path.name)):
            yield match[1], path.name, match[2], _kirkland_asset(path.name)


def _archive_manuals(content):
    document = json.loads(content)
    if document.get("metadata", {}).get("identifier") != ARCHIVE_ITEM:
        raise ValueError("Unexpected Internet Archive PlayStation manual item")
    for item in document["files"]:
        if (item.get("source") == "original" and not item.get("private")
                and (match := MANUAL_NAME.fullmatch(item["name"]))):
            yield match[1], item["name"], match[2], {
                "url": f"https://archive.org/download/{ARCHIVE_ITEM}/" + quote(item["name"]),
                "source": "Sony PlayStation Manuals", "sourceUrl": ARCHIVE,
                "sha1": item.get("sha1"), "size": int(item["size"]),
            }


def manual_inventory(directory, supplemental):
    kirkland = read_index(directory / "kirkland-ps1.html", KIRKLAND + "index.html")
    archive = read_index(directory / "ia-playstation-manuals.json", f"https://archive.org/metadata/{ARCHIVE_ITEM}")
    manuals = [*_archive_manuals(archive.content), *_catalogue_manuals(kirkland.content)]
    for filename, checksum in supplemental.items():
        if not (match := MANUAL_NAME.fullmatch(filename)) or PurePosixPath(filename).name != filename:
            raise ValueError(f"Invalid reviewed PlayStation manual: {filename!r}")
        manuals.append((match[1], filename, match[2], _kirkland_asset(filename, **checksum)))
    return manuals, [kirkland, archive]


def add_manuals(catalog, manuals, reviews):
    by_name, by_title = defaultdict(list), defaultdict(list)
    for title, filename, variant, asset in manuals:
        item = (bool(variant), asset.get("size") is None, filename, asset)
        by_name[filename].append(item)
        by_title[_compact_title(title)].append(item)
    claims, names = defaultdict(set), {}
    for game in catalog["games"]:
        release, = game["releases"]
        titles = {*release["titles"], *(archive["title"] for archive in release.get("archives", ())
                                       if archive["basis"] not in {"reviewed-retail-bundle", "reviewed-retail-pressing"})}
        names[game["key"]] = {_compact_title(title) for title in titles}
        for title in names[game["key"]]:
            claims[title].add(game["key"])
    for game in catalog["games"]:
        release, = game["releases"]
        review = reviews.get(game["source"]["record"], {})
        if files := review.get("manuals"):
            if any(not by_name[filename] for filename in files):
                raise ValueError(f"Unknown reviewed PlayStation manuals for {game['title']!r}")
            selected = [(MANUAL_NAME.fullmatch(name)[1], pick_manual(by_name[name])) for name in files]
        else:
            options = [item for title in names[game["key"]]
                       if claims[title] == {game["key"]} for item in by_title[title]]
            selected = [(game["title"], pick_manual(options))] if options else []
        available = {archive["title"] for archive in release.get("archives", ())
                     if archive["basis"] == "reviewed-retail-pressing"}
        for title, pressing in review.get("pressings", {}).items():
            if title in available and (filename := pressing.get("manual")):
                if filename not in by_name:
                    raise ValueError(f"Unknown reviewed PlayStation manual: {filename!r}")
                selected.append((pressing["label"], pick_manual(by_name[filename])))
        if selected:
            release["manuals"] = [{**asset, "name": name, "format": "PDF", "regions": ["US"]}
                                  for name, asset in selected]


def pick_manual(options):
    return min(options, key=lambda item: (*item[:3], item[3]["url"]))[3]


def apply_reviewed_artwork(catalog, reviews):
    for game in catalog["games"]:
        if artwork := reviews.get(game["source"]["record"], {}).get("artwork"):
            release, = game["releases"]
            release.setdefault("artwork", {}).update({
                kind: {**asset, "basis": "reviewed-image"} for kind, asset in artwork.items()
            })
