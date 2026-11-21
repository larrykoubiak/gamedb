"""Read the source titles and module naming conventions in UnExoticA."""

import re
import unicodedata
from pathlib import PurePosixPath

from .archives import open_vgm_location

AMIGA = ("Commodore", "Amiga")
AMIGA_CD32 = ("Commodore", "Amiga CD32")
AMIGA_CDTV = ("Commodore", "Amiga CDTV")
AMIGA_PLATFORMS = {"cd32": AMIGA_CD32, "cdtv": AMIGA_CDTV}

MACHINE_MARKER = re.compile(r"cd(?:32|tv)(?![a-z0-9])")
DISC_SUFFIX = re.compile(r"\s*[(\[-]?\s*(?:cd32|cdtv)\s*[)\]]?\s*$", re.IGNORECASE)
NOTE_FIELDS = {"source type", "source title", "alternative titles", "format", "publisher", "year"}

# These are replay prefixes in UnExoticA, not extensions to append to the source.
MODULE_PREFIXES = frozenset("""
    abk ac1d agi amc bd bds bp bss chan cin cm core cus cust dh di dl dln dm2
    dmu dns dsc dsr dw dz fc13 fw gmc han hd hip hipc ims jcb jd jmf jo jpn jt
    kh lme mc mcr mcs md mdat med mfp mmdc mod mok mon mug mug2 mw mxtx np2 np3
    ntp okt osp p41a p4x p60 pap pha pp21 pro prun pru2 ps puma pvp rh rh2 rho
    rjp rk sa sb scn sct scr scumm sdr sfx sid sid2 sjs sm smus snk snx spl
    tf thm tiny tp3 tw uds us wb
""".split())
SAMPLE_PREFIXES = frozenset({"8svx", "ins", "instr", "smp", "smpl"})


def module_format(name):
    """Return the prefix format and whether this member is a companion sample."""
    path = PurePosixPath(name)
    prefix, dot, _ = path.name.strip().casefold().partition(".")
    suffix = path.suffix.strip().casefold().lstrip(".")
    if suffix in SAMPLE_PREFIXES:
        return suffix, True
    if dot and prefix in (SAMPLE_PREFIXES | MODULE_PREFIXES):
        # UnExoticA's SID prefix identifies the Benn Daglish replayer.
        return ("bds" if prefix == "sid" else prefix), prefix in SAMPLE_PREFIXES
    if suffix in MODULE_PREFIXES:
        return ("bds" if suffix == "sid" else suffix), False
    return None, False


def read_notes(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    lines = text.splitlines()
    fields = {}
    short_fields = {"type": "source type", "title": "source title"}
    for line in lines:
        field, separator, value = line.partition(":")
        field = field.strip().casefold()
        key = short_fields.get(field, field)
        if separator and key in NOTE_FIELDS:
            fields.setdefault(key, value.strip())
    for field, value in zip(lines, lines[1:]):
        field = field.strip().casefold()
        if field in NOTE_FIELDS:
            fields.setdefault(field, value.strip())
    return fields


def note_fields(root, asset):
    with open_vgm_location(root, asset) as stream:
        return read_notes(stream.read(64 * 1024))


def archived_game_alias(root, album):
    """Use the rip's own shorter game title when its CD machine agrees."""
    for asset in album.assets:
        if asset["format"] != "txt" or not asset.get("archive_format"):
            continue
        try:
            info = note_fields(root, asset)
        except (OSError, ValueError):
            continue
        title = unicodedata.normalize("NFKC", info.get("source title", ""))
        if info.get("source type", "").casefold() != "game":
            continue
        markers = set(MACHINE_MARKER.findall(title.casefold()))
        if len(markers) != 1 or AMIGA_PLATFORMS[next(iter(markers))] != album.system:
            continue
        short = DISC_SUFFIX.sub("", title).strip()
        if short and album.title.casefold().startswith((f"{short.casefold()} - ", f"{short.casefold()}: ")):
            return short, asset["member_name"]
    return None


def apply_game_notes(root, album):
    notes = next((asset for asset in album.assets
                  if asset["format"] == "txt" and not asset["member_no"]), None)
    if notes is None:
        return
    try:
        info = note_fields(root, notes)
    except (OSError, ValueError):
        album.issues.append("UnExoticA source notes could not be read")
        return
    title = info.get("source title")
    if info.get("source type", "").casefold() != "game" or not title:
        return

    alias = info.get("alternative titles", "")
    markers = set(MACHINE_MARKER.findall(unicodedata.normalize(
        "NFKC", f"{title} {album.source_name}"
    ).casefold()))
    if len(markers) > 1:
        album.issues.append("UnExoticA source names specify conflicting disc platforms")
        return
    if markers:
        album.system = AMIGA_PLATFORMS[markers.pop()]
        title = DISC_SUFFIX.sub("", unicodedata.normalize("NFKC", title)).strip()
        alias = DISC_SUFFIX.sub("", unicodedata.normalize("NFKC", alias)).strip()
    elif "cdda" in album.source_name.casefold():
        album.issues.append("UnExoticA CD audio has no explicit disc platform")
        return
    if not title:
        return
    album.title = title
    album.aliases = (alias,) if alias and alias != title else ()
    album.review_only = False
    album.match_basis = "unexotica_game_notes"
    album.source_evidence = {
        "unexoticaSourceTitle": info["source title"],
        "unexoticaNotes": notes["source_path"],
        **{field: info[field] for field in ("format", "publisher", "year") if info.get(field)},
    }
