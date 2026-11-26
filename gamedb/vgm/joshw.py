"""Platform and title evidence in the HCS64 index of JoshW music sets."""

import re
from pathlib import PurePosixPath


COLLECTION = "JoshW"
PSF_COLLECTION = "The PlayStation Music Collection PSF"
INDEX_URL = "https://vgm.hcs64.com/index-clean.json"
RETAIL_BUCKETS = {"dreamcast": "dsf", "playstation2": "psf2", "gamecube": "gcn", "cdi": "cdi"}
DEFAULT_SYSTEMS = {
    "spc": ("Nintendo", "Super Nintendo Entertainment System"),
    "nsf": ("Nintendo", "Nintendo Entertainment System"),
    "gbs": ("Nintendo", "Game Boy"),
    "usf": ("Nintendo", "Nintendo 64"),
    "ssf": ("Sega", "Saturn"),
    "gsf": ("Nintendo", "Game Boy Advance"),
    "2sf": ("Nintendo", "Nintendo DS"),
    "psf": ("Sony", "PlayStation"),
    "3do": ("The 3DO Company", "3DO Interactive Multiplayer"),
    "cdi": ("Philips", "CD-i"),
    "dsf": ("Sega", "Dreamcast"),
    "gcn": ("Nintendo", "GameCube"),
    "psf2": ("Sony", "PlayStation 2"),
}
CARTRIDGES = {
    "smd": {"smd": ("Sega", "Mega Drive"), "32x": ("Sega", "32X"), "pico": ("Sega", "Pico")},
    "hes": {"pce": ("NEC", "PC Engine / TurboGrafx-16"), "sgx": ("NEC", "SuperGrafx")},
    "wsr": {"ws": ("Bandai", "WonderSwan"), "wsc": ("Bandai", "WonderSwan Color")},
}
KSS_SYSTEMS = {name: ("Sega", name) for name in ("Game Gear", "Master System")}
DOMAINS = DEFAULT_SYSTEMS.keys() | CARTRIDGES.keys() | {"kss"}
BRACKET = re.compile(r"\[([^\[\]]+)\]")
TRAILING_TAGS = re.compile(r"(?:\s*\[[^\[\]]+\])+$")
RELEASE_DATE = re.compile(r"\s*\((?:19|20)[0-9x]{2}(?:-\d{1,2}){0,2}\)", re.IGNORECASE)
VARIANTS = re.compile(r"(?:\s*\((?:conv|[a-d]|SGB|SMS|SG-1000|64DD|DSiWare|Repaired)\))+$", re.IGNORECASE)
EDITION = re.compile(r"\s*\((?:alpha|beta|demo|milestone|preview|prototype|sample|trial|unreleased)\b[^()]*\)$", re.IGNORECASE)
REVISION = re.compile(r"\s*\(v(\d+(?:\.\d+)+)\)$", re.IGNORECASE)
AMIGA_DISC = re.compile(r"\((cd32|cdtv)\)", re.IGNORECASE)
FIX_LABEL = re.compile(r"\s+\[fixed\]", re.IGNORECASE)
PLATFORM_NOTES = {
    "spc": {"snes", "snsf", "sgb"}, "nsf": {"nes", "fds", "vs", "arcade"},
    "gbs": {"gb", "gbc", "sgb"}, "usf": {"n64", "64dd", "n64dd"}, "gsf": {"gba"},
    "2sf": {"nds", "dsi", "dsiware", "ncsf"}, "smd": {*CARTRIDGES["smd"], "scd"},
    "hes": {*CARTRIDGES["hes"], "tcd", "pc-fx", "pc-fxga"}, "wsr": set(CARTRIDGES["wsr"]),
    "kss": {"gg", "sms", "sg-1000"}, "cdi": {"cd-i", "jaguar", "amiga", "cd32", "cdtv"},
    "psf": {"ps1", "psx", "psf"},
    "ssf": {"sat", "saturn", "ssf"}, "3do": {"3do"},
    "dsf": {"dc", "dsf"}, "gcn": {"gcn", "gc"}, "psf2": {"ps2", "psf2"},
}
OTHER_NOTES = {"a", "ab", "alt", "en", "eu", "fixed", "jp", "mod", "rr", "tagged", "us", "ut", "z0", "z1"}


def platform(domain, path):
    """Read the machine from a supported archive's platform tags and folder."""
    stem = path.stem.casefold()
    tags = {tag.casefold() for tag in BRACKET.findall(path.stem)}
    if ((domain == "smd" and "scd" in tags)
            or (domain == "hes" and tags & {"tcd", "pc-fx", "pc-fxga"})):
        return None
    if domain in CARTRIDGES:
        # A port can be identified before the date even where its final archive
        # tag uses the family name, such as [32X] ... [SMD].
        return next((value for tag, value in reversed(CARTRIDGES[domain].items()) if tag in tags), None)
    if domain == "kss":
        if path.parts[0] == "Master System" and "(sg-1000)" in stem:
            return "Sega", "SG-1000"
        return KSS_SYSTEMS.get(path.parts[0])
    if domain == "cdi":
        if path.parts[0] == "cdi" and "cd-i" in tags:
            return DEFAULT_SYSTEMS["cdi"]
        if path.parts[0] == "amiga" and "amiga" in tags:
            discs = (tags & {"cd32", "cdtv"}) | set(AMIGA_DISC.findall(stem))
            if len(discs) > 1:
                return None
            disc = next(iter(discs), "")
            return "Commodore", f"Amiga {disc.upper()}" if disc else "Amiga"
        return ("Atari", "Jaguar") if path.parts[0] == "jaguar" and "jaguar" in tags else None
    if domain == "gbs" and "gbc" in tags:
        return "Nintendo", "Game Boy Color"
    if domain == "nsf":
        if "fds" in tags:
            return "Nintendo", "Famicom Disk System"
        if "vs" in tags or "(arcade)" in stem:
            return "Various", "Arcade"
    if domain == "spc" and stem.startswith("bs "):
        return "Nintendo", "Satellaview"
    if domain == "ssf" and (tags & {"stv", "st-v", "arcade"} or re.search(r"\((?:st-?v|arcade)\)", stem)):
        return None
    if domain == "dsf" and (tags & {"naomi", "atomiswave", "arcade"}
                            or re.search(r"\((?:naomi|atomiswave|arcade)\)", stem)):
        return None
    if domain == "usf" and (tags & {"64dd", "n64dd"} or "(64dd)" in stem or "(randnetdd)" in stem
                            or stem.startswith("mario artist paint studio ")):
        return "Nintendo", "Nintendo 64DD"
    if domain == "2sf" and (tags & {"dsi", "dsiware"} or "(dsiware)" in stem):
        return "Nintendo", "Nintendo DSi"
    return DEFAULT_SYSTEMS.get(domain)


def soundtrack_name(domain, path):
    stem = path.stem
    # Some undated 64DD sets still separate the title from the credits.
    if domain == "usf" and (edition := re.search(r"\(64DD\)\(", stem, re.IGNORECASE)):
        return stem[:edition.start()].strip(), ()
    title_end = RELEASE_DATE.search(stem)
    if title_end:
        label = stem[:title_end.start()].strip()
    else:
        label = TRAILING_TAGS.sub("", stem).strip()
    notes = PLATFORM_NOTES.get(domain, set()) | OTHER_NOTES
    aliases = tuple(value for tag in BRACKET.findall(label) if (value := tag.strip()) and value.casefold() not in notes)
    title = " ".join(BRACKET.sub("", label).split())
    title = VARIANTS.sub("", title).strip() or stem
    if domain == "cdi":
        title = AMIGA_DISC.sub("", title).strip()
    if edition := EDITION.search(title):
        aliases = tuple(alias if EDITION.search(alias) else f"{alias} {edition[0].strip()}" for alias in aliases)
    if "fixed" in {tag.casefold() for tag in BRACKET.findall(stem)}:
        title += " [fixed]"
    return title, aliases


def title_revision(title):
    """Separate a rip label and explicit version from the full game title."""
    title = title.removesuffix(" [fixed]")
    if version := REVISION.search(title):
        return title[:version.start()], version[1]
    return title, None


def superseded_sources(names):
    """Find the exact source filenames replaced by an upstream fix."""
    return {original for name in names if (original := FIX_LABEL.sub("", name)) != name}


def prefer_playstation_sources(albums):
    """Prefer the matching JoshW archive when it covers the same releases."""
    upstream = {}
    for album in albums:
        if (album["collection"] == COLLECTION and album["sourceName"].startswith("psf/")
                and any(asset["kind"] == "track" for asset in album["assets"])):
            name = album["sourceName"]
            upstream.setdefault(PurePosixPath(name).name, set()).update(album.get("releases", ()))
    return [album for album in albums
            if album["collection"] != PSF_COLLECTION
            or (name := album["sourceName"]) not in upstream
            or not set(album.get("releases", ())).issubset(upstream[name])]


def supports_version(system, version, facts):
    facts = {(kind, value.strip().casefold().removeprefix("v")) for kind, value in facts}
    if ("version", version) in facts or ("revision", version) in facts:
        return True
    # USF labels the Nintendo 64 ROM revision v1.x. Catalog DATs also call it Rev x.
    if system == DEFAULT_SYSTEMS["usf"] and version.startswith("1.") and version.count(".") == 1:
        return ("revision", version.partition(".")[2]) in facts
    return False


def parse_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.as_posix() != value or "\\" in value or "\x00" in value
            or any(part.startswith(".") for part in path.parts)
            or any(part.startswith("@") for part in path.parts[:-1])
            or path.is_absolute()):
        raise ValueError(f"Invalid JoshW path: {value!r}")
    return path
