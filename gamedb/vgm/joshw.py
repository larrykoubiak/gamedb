"""Platform and title evidence in the HCS64 index of JoshW music sets."""

import re
from pathlib import PurePosixPath


COLLECTION = "JoshW"
INDEX_URL = "https://vgm.hcs64.com/index-clean.json"
DEFAULT_SYSTEMS = {
    "spc": ("Nintendo", "Super Nintendo Entertainment System"),
    "nsf": ("Nintendo", "Nintendo Entertainment System"),
    "gbs": ("Nintendo", "Game Boy"),
    "usf": ("Nintendo", "Nintendo 64"),
    "gsf": ("Nintendo", "Game Boy Advance"),
    "2sf": ("Nintendo", "Nintendo DS"),
}
CARTRIDGES = {
    "smd": {"smd": ("Sega", "Mega Drive"), "32x": ("Sega", "32X"), "pico": ("Sega", "Pico")},
    "hes": {"pce": ("NEC", "PC Engine / TurboGrafx-16"), "sgx": ("NEC", "SuperGrafx")},
    "wsr": {"ws": ("Bandai", "WonderSwan"), "wsc": ("Bandai", "WonderSwan Color")},
}
KSS_SYSTEMS = {name: ("Sega", name) for name in ("Game Gear", "Master System")}
DOMAINS = DEFAULT_SYSTEMS.keys() | CARTRIDGES.keys() | {"kss", "cdi"}
BRACKET = re.compile(r"\[([^\[\]]+)\]")
TRAILING_TAGS = re.compile(r"(?:\s*\[[^\[\]]+\])+$")
RELEASE_DATE = re.compile(r"\s*\((?:19|20)[0-9x]{2}(?:-\d{1,2}){0,2}\)", re.IGNORECASE)
VARIANTS = re.compile(r"(?:\s*\((?:conv|[a-d]|SGB|SMS|SG-1000|64DD|DSiWare|Repaired)\))+$", re.IGNORECASE)
EDITION = re.compile(r"\s*\((?:alpha|beta|demo|milestone|preview|prototype|sample|trial|unreleased)\b[^()]*\)$", re.IGNORECASE)
PLATFORM_NOTES = {
    "spc": {"snes", "snsf", "sgb"}, "nsf": {"nes", "fds", "vs", "arcade"},
    "gbs": {"gb", "gbc", "sgb"}, "usf": {"n64", "64dd", "n64dd"}, "gsf": {"gba"},
    "2sf": {"nds", "dsi", "dsiware", "ncsf"}, "smd": {*CARTRIDGES["smd"], "scd"},
    "hes": {*CARTRIDGES["hes"], "tcd", "pc-fx", "pc-fxga"}, "wsr": set(CARTRIDGES["wsr"]),
    "kss": {"gg", "sms", "sg-1000"}, "cdi": {"jaguar"},
}
OTHER_NOTES = {"a", "ab", "alt", "en", "eu", "jp", "mod", "rr", "tagged", "us", "ut", "z0", "z1"}


def platform(domain, path):
    """Select the non-optical console and handheld collections."""
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
    if edition := EDITION.search(title):
        aliases = tuple(alias if EDITION.search(alias) else f"{alias} {edition[0].strip()}" for alias in aliases)
    return title, aliases


def parse_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.as_posix() != value or "\\" in value or "\x00" in value
            or any(part.startswith(".") for part in path.parts)
            or any(part.startswith("@") for part in path.parts[:-1])
            or path.is_absolute()):
        raise ValueError(f"Invalid JoshW path: {value!r}")
    return path
