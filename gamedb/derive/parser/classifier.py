"""Classify extracted tags using collection-specific naming conventions.

Input spelling, source order and offsets stay in archive_name.tags. These are
interpretations of source claims, not independently verified software metadata.
"""

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from .config import COLLECTIONS


REFERENCE_DIRECTORY = Path(__file__).resolve().parents[3] / "data" / "reference"
_vocabulary_bytes = (REFERENCE_DIRECTORY / "tag_vocabulary.json").read_bytes()
VOCABULARY = json.loads(_vocabulary_bytes)
CLASSIFIER_VERSION = "3:" + hashlib.sha256(_vocabulary_bytes).hexdigest()[:12]
LANGUAGES = frozenset(VOCABULARY["languages"])
REDUMP_REGIONS = VOCABULARY["redump_regions"]
REDUMP_SATURN_DISC_CODE = re.compile(VOCABULARY["redump_saturn_disc_code_pattern"])
REDUMP_MEDIA_LABELS = frozenset(VOCABULARY["redump_media_labels"])
REDUMP_DEMO_STATUS = VOCABULARY["redump_demo_status"]
REDUMP_SYSTEMS = frozenset(VOCABULARY["redump_systems"])
TOSEC_REGIONS = frozenset(VOCABULARY["tosec_regions"])
TOSEC_SYSTEMS = frozenset(VOCABULARY["tosec_systems"])
TOSEC_VIDEO = frozenset(VOCABULARY["tosec_video"])
TOSEC_MEDIA_LABELS = frozenset(VOCABULARY["tosec_media_labels"])
NO_INTRO_SYSTEMS = frozenset(VOCABULARY["no_intro_systems"])
NO_INTRO_RELEASE_STATUS = VOCABULARY["no_intro_release_status"]
NO_INTRO_DISTRIBUTION_CHANNELS = VOCABULARY["no_intro_distribution_channels"]
NO_INTRO_MEDIA_LABELS = frozenset(VOCABULARY["no_intro_media_labels"])
DATE = re.compile(r"[12][0-9x]{3}(?:-[0-9x]{2}){0,2}", re.IGNORECASE)
VERSION = re.compile(r"(?P<identifier>v)\s*(?P<value>\d[\w.+-]*)", re.IGNORECASE)
REVISION = re.compile(
    r"(?P<identifier>rev(?:ision)?\.?)\s+(?P<value>[A-Za-z0-9][\w.+-]*)",
    re.IGNORECASE,
)
MEDIA = re.compile(
    r"(?:(?P<label>(?!(?:CD-Rom|CD-ROM|Disc|Disk|File|Part|Side|Tape) )[A-Za-z][A-Za-z0-9+&' .-]*?) )?"
    r"(?P<type>CD-Rom|CD-ROM|Disc|Disk|File|Part|Side|Tape) "
    r"(?P<part>[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)"
    r"(?: of (?P<total>[A-Za-z0-9]+))?"
    r"(?: Side (?P<side>[A-Za-z0-9]+))?"
    r"(?:\s*[-,]\s*(?P<description>.+))?"
)
DUMP = re.compile(r"(cr|tr|f|h|m|p|t|o|u|v|b|a|!)(\d*)(?: (.+))?")
DUMP_CODES = {
    "cr": ("dump_modification", "cracked"), "f": ("dump_modification", "fixed"),
    "h": ("dump_modification", "hacked"), "m": ("dump_modification", "modified"),
    "p": ("dump_modification", "pirated"), "t": ("dump_modification", "trained"),
    "tr": ("dump_modification", "translated"), "o": ("dump_status", "overdump"),
    "u": ("dump_status", "underdump"), "v": ("dump_status", "virus"),
    "b": ("dump_status", "bad"), "a": ("dump_status", "alternate"),
    "!": ("dump_status", "verified"),
}
TRANSLATION_VERSION = re.compile(
    r"(?:^|\s)v\s*(?P<version>\d[\w.+-]*)",
    re.IGNORECASE,
)
TRANSLATION_REVISION = re.compile(
    r"(?:^|\s)rev(?:ision)?\.?\s+(?P<revision>[A-Za-z0-9][\w.+-]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClassifiedTags:
    tags: list[dict]
    issues: tuple[str, ...]


def _known(category, rule, **details):
    return {"category": category, "status": "classified", "rule": rule, "details": details}


def _unknown(reason="no_matching_rule"):
    return {"category": "unknown", "status": "unclassified", "rule": reason, "details": {}}


def _translation_details(detail):
    """Extract explicit TOSEC translation language/version claims."""

    if not detail:
        return {}
    language_token = detail.split(maxsplit=1)[0].rstrip(",").lower()
    partial = language_token.endswith("-partial")
    if partial:
        language_token = language_token.removesuffix("-partial")
    language_codes = [code for code in re.split(r"[-,]", language_token) if code]

    result = {}
    if language_codes and all(code in LANGUAGES for code in language_codes):
        result["language_codes"] = language_codes
        if partial:
            result["translation_status"] = "partial"
    version = TRANSLATION_VERSION.search(detail)
    if version:
        result["version"] = version.group("version")
    return result


def _source(classification, identifier, value):
    classification["identifier"] = identifier
    classification["value"] = value
    return classification


def _source_defaults(tags, classifications):
    for raw_tag, classification in zip(tags, classifications):
        classification.setdefault("identifier", None)
        classification.setdefault("value", raw_tag["value"])
    return classifications


def _date_details(value):
    if not DATE.fullmatch(value):
        return None
    parts = value.lower().split("-")
    # Partial dates stay partial; do not replace unknown digits with defaults.
    if len(parts) >= 2 and "x" not in parts[1] and not 1 <= int(parts[1]) <= 12:
        return None
    if len(parts) == 3 and "x" not in parts[2] and not 1 <= int(parts[2]) <= 31:
        return None
    if len(parts) == 3 and "x" not in value.lower():
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
    return {"text": value, "precision": ("year", "month", "day")[len(parts) - 1], "has_unknown_digits": "x" in value.lower()}


def _version(value, prefix):
    match = VERSION.fullmatch(value)
    if match:
        return _source(
            _known("version", prefix + ".version", text=match["value"]),
            match["identifier"], match["value"],
        )
    match = REVISION.fullmatch(value)
    if match:
        return _source(
            _known("revision", prefix + ".revision", text=match["value"]),
            match["identifier"], match["value"],
        )
    return None


def _common_parenthesized(value, prefix):
    languages = value.split(",")
    if all(re.fullmatch(r"[A-Z][a-z]", item) and item.lower() in LANGUAGES for item in languages):
        return _known("language", prefix + ".language", codes=[item.lower() for item in languages])
    date_details = _date_details(value)
    if date_details:
        return _known("release_date", prefix + ".release_date", **date_details)
    version = _version(value, prefix)
    if version:
        return version
    status = re.fullmatch(r"(Beta|Demo|Proto|Sample)(?: (\d+))?", value)
    if status:
        details = {
            "code": {
                "Beta": "beta", "Demo": "demo", "Proto": "prototype", "Sample": "sample",
            }[status[1]],
        }
        if status[2]:
            details["variant"] = int(status[2])
        return _source(
            _known("release_status", prefix + ".release_status", **details),
            status[1], status[2],
        )
    if value == "Unl":
        return _source(_known("license", prefix + ".unlicensed", code="unlicensed"), "Unl", None)
    alternate = re.fullmatch(r"Alt(?: (\d+))?", value)
    if alternate:
        details = {"code": "alternate"}
        if alternate[1]:
            details["variant"] = int(alternate[1])
        return _source(
            _known("dump_status", prefix + ".alternate", **details),
            "Alt", alternate[1],
        )
    return None


def _media(value, prefix):
    match = MEDIA.fullmatch(value)
    if not match:
        return None
    media_type = match["type"].lower().replace("-", "_")
    details = {"type": media_type, "part": match["part"]}
    if match["label"]:
        details["label"] = match["label"]
    if match["total"]:
        if match["total"].isdigit():
            details["total"] = int(match["total"])
        else:
            details["total_label"] = match["total"]
            details["total_unknown"] = True
    if match["side"]:
        details["side"] = match["side"]
    if match["description"]:
        details["description"] = match["description"]
    return _source(
        _known("media", prefix + ".media", **details),
        match["type"], match["part"],
    )


def _no_intro(tag, region_seen):
    value, delimiter = tag["value"], tag["delimiter"]
    if delimiter == "[]":
        if value == "BIOS" and tag["start"] == 0:
            return _source(_known("bios", "no_intro.bios"), "BIOS", None)
        if value == "b":
            return _source(
                _known("dump_status", "no_intro.bad_or_hacked", code="bad_or_hacked"),
                "b", None,
            )
        if value == "MIA":
            return _source(
                _known("dump_status", "no_intro.missing_dump", code="missing"),
                "MIA", None,
            )
        return _unknown()
    if delimiter != "()":
        return _unknown()
    regions = value.split(", ")
    if not region_seen and all(item in VOCABULARY["no_intro_regions"] for item in regions):
        return _known("region", "no_intro.region", codes=[VOCABULARY["no_intro_regions"][item] for item in regions])
    if not region_seen and value == "Unknown":
        return _known("region", "no_intro.unknown_region", codes=[], unknown=True)
    if not region_seen:
        return _unknown("no_intro.missing_region_context")
    common = _common_parenthesized(value, "no_intro")
    if common:
        return common
    media = _media(value, "no_intro")
    if media:
        return media
    if value in NO_INTRO_SYSTEMS:
        return _known("system_requirement", "no_intro.system", text=value)
    if value in NO_INTRO_RELEASE_STATUS:
        return _source(
            _known("release_status", "no_intro.named_status", code=NO_INTRO_RELEASE_STATUS[value]),
            value, None,
        )
    if value in NO_INTRO_DISTRIBUTION_CHANNELS:
        return _source(
            _known(
                "distribution_channel", "no_intro.distribution_channel",
                code=NO_INTRO_DISTRIBUTION_CHANNELS[value],
            ),
            value, None,
        )
    if value in NO_INTRO_MEDIA_LABELS:
        return _known("media_label", "no_intro.media_label", text=value)
    if value in VOCABULARY["no_intro_special"]:
        return _source(_known("special", "no_intro.special", code=value), value, None)
    # Optional Additional, Special and status fields can all contain free text.
    # Position alone cannot disambiguate these No-Intro fields.
    return _unknown()


def _english_translation(tag, region_seen):
    """Interpret Maybe-Intro's No-Intro-derived English naming profile."""
    value, delimiter = tag["value"], tag["delimiter"]
    if delimiter == "[]":
        if "T-En" in value or value.startswith("En Dub"):
            details = {
                "code": "translated",
                "language_codes": ["en"],
                "detail": value,
            }
            version = TRANSLATION_VERSION.search(value)
            if version:
                details["version"] = version.group("version")
            revision = TRANSLATION_REVISION.search(value)
            if revision:
                details["revision"] = revision.group("revision")
            if "Hack" in value:
                details["additional_modifications"] = ["hacked"]
            if "+Fix" in value:
                details.setdefault("additional_modifications", []).append("fixed")
            identifier = "En Dub" if value.startswith("En Dub") else "T-En"
            return _source(
                _known(
                    "dump_modification", "english_translations.translation",
                    **details,
                ),
                identifier, value.removeprefix(identifier).strip() or None,
            )
        if value == "i":
            return _source(
                _known(
                    "release_status", "english_translations.incomplete",
                    code="incomplete_translation",
                ),
                "i", None,
            )
        if value == "n":
            return _source(
                _known(
                    "special", "english_translations.localized_title",
                    code="localized_title",
                ),
                "n", None,
            )
        if "Hack" in value:
            return _source(
                _known(
                    "dump_modification", "english_translations.hack",
                    code="hacked", detail=value,
                ),
                value.split(maxsplit=1)[0], value,
            )
        return _known(
            "additional", "english_translations.additional", text=value
        )
    inherited = _no_intro(tag, region_seen)
    if inherited["status"] == "classified" or not region_seen:
        return inherited
    if delimiter == "()" and "Hack" in value:
        return _source(
            _known(
                "dump_modification", "english_translations.variant_hack",
                code="hacked", detail=value,
            ),
            "Hack", value,
        )
    if delimiter == "()":
        return _known(
            "additional", "english_translations.variant", text=value
        )
    return inherited


def _tosec_optional(tag):
    value, delimiter = tag["value"], tag["delimiter"]
    if delimiter == "[]":
        match = DUMP.fullmatch(value)
        if match:
            category, code = DUMP_CODES[match[1]]
            details = {"code": code, "flag": match[1]}
            if match[2]:
                details["variant"] = int(match[2])
            if match[3]:
                # Descriptors may be groups, people, reasons or combinations.
                details["detail"] = match[3]
                if match[1].lower() == "tr":
                    details.update(_translation_details(match[3]))
            return _source(
                _known(category, "tosec.dump_flag", **details),
                match[1], match[3],
            )
        return _known("additional", "tosec.more_info", text=value)
    if delimiter != "()":
        return _unknown()
    version = _version(value, "tosec")
    if version:
        return version
    if value in TOSEC_SYSTEMS:
        return _known("system_requirement", "tosec.system", text=value)
    if value in TOSEC_VIDEO:
        return _known("video", "tosec.video", text=value)
    if value in TOSEC_MEDIA_LABELS:
        return _known("media_label", "tosec.media_label", text=value)
    countries = value.split("-")
    if all(item in TOSEC_REGIONS for item in countries):
        return _known("region", "tosec.country", codes=countries)
    languages = value.split("-")
    if all(item in LANGUAGES for item in languages):
        return _known("language", "tosec.language", codes=languages)
    if re.fullmatch(r"M[3-9]\d*|M[12]\d+", value):
        return _source(
            _known("language", "tosec.language_count", count=int(value[1:])),
            "M", value[1:],
        )
    if value in VOCABULARY["tosec_copyright"]:
        return _source(
            _known("copyright_status", "tosec.copyright", code=VOCABULARY["tosec_copyright"][value]),
            value, None,
        )
    if value == "MIT":
        return _source(_known("license", "tosec.mit_license", code="mit"), "MIT", None)
    if value in ("alpha", "beta", "preview", "pre-release", "proto"):
        return _source(
            _known("release_status", "tosec.development", code={"proto": "prototype", "pre-release": "pre_release"}.get(value, value)),
            value, None,
        )
    media = _media(value, "tosec")
    if media:
        return media
    return _unknown()


def _redump(tag, region_seen):
    value, delimiter = tag["value"], tag["delimiter"]
    if delimiter != "()":
        return _unknown()
    if not region_seen:
        regions = value.split(", ")
        if all(item in REDUMP_REGIONS for item in regions):
            return _known(
                "region",
                "redump.region",
                codes=[REDUMP_REGIONS[item] for item in regions],
            )
        if value == "Unknown":
            return _known("region", "redump.unknown_region", codes=[], unknown=True)
        return _unknown("redump.missing_region_context")
    common = _common_parenthesized(value, "redump")
    if common:
        return common
    if REDUMP_SATURN_DISC_CODE.fullmatch(value):
        return _known(
            "media_label", "redump.saturn_disc_code",
            scheme="saturn_disc_code", codes=value.split(", "),
        )
    if value in REDUMP_MEDIA_LABELS:
        return _known("media_label", "redump.media_label", text=value)
    if value in REDUMP_DEMO_STATUS:
        return _source(
            _known("release_status", "redump.demo_status", code=REDUMP_DEMO_STATUS[value]),
            value, None,
        )
    if value in REDUMP_SYSTEMS:
        return _known("system_requirement", "redump.system", text=value)
    media = _media(value, "redump")
    if media:
        return media
    return _unknown()


def classify_tags(romset, archive_name, tags, parse_status="parsed"):
    if romset not in COLLECTIONS:
        classified = [_unknown("unsupported_collection") for tag in tags]
        return ClassifiedTags(_source_defaults(tags, classified), ("unsupported_collection",))
    if parse_status != "parsed":
        classified = [_unknown("source_parse_review") for tag in tags]
        return ClassifiedTags(_source_defaults(tags, classified), ("source_parse_review",))
    classified = [_unknown() for tag in tags]
    issues = []
    if romset in ("No-Intro", "English Translations"):
        region_seen = False
        for index, tag in enumerate(tags):
            classified[index] = (
                _english_translation(tag, region_seen)
                if romset == "English Translations"
                else _no_intro(tag, region_seen)
            )
            region_seen |= classified[index]["category"] == "region"
        if not region_seen:
            issues.append("missing_region")
    elif romset == "Redump":
        region_seen = False
        for index, tag in enumerate(tags):
            classified[index] = _redump(tag, region_seen)
            region_seen |= classified[index]["category"] == "region"
        if not region_seen:
            issues.append("missing_region")
    else:
        # A bare version and optional demo can precede the mandatory date/publisher.
        index = 0
        if index < len(tags) and tags[index]["delimiter"] == "":
            classified[index] = _version(tags[index]["value"], "tosec") or _unknown()
            index += 1
        if index < len(tags) and tags[index]["delimiter"] == "()" and tags[index]["value"] in ("demo", "demo-kiosk", "demo-playable", "demo-rolling", "demo-slideshow"):
            demo_value = tags[index]["value"]
            classified[index] = _source(
                _known("demo", "tosec.demo", code=demo_value),
                "demo", demo_value.removeprefix("demo-") if demo_value != "demo" else None,
            )
            index += 1
        date_details = _date_details(tags[index]["value"]) if index < len(tags) and tags[index]["delimiter"] == "()" else None
        if date_details is None or index + 1 >= len(tags) or tags[index + 1]["delimiter"] != "()":
            issues.append("missing_date_publisher_context")
        else:
            classified[index] = _known("release_date", "tosec.date_position", **date_details)
            publisher = tags[index + 1]["value"]
            classified[index + 1] = _known("publisher", "tosec.publisher_position", text=None if publisher == "-" else publisher, unknown=publisher == "-")
            for cursor in range(index + 2, len(tags)):
                classified[cursor] = _tosec_optional(tags[cursor])
    if any(tag["status"] == "unclassified" for tag in classified):
        issues.append("unclassified_tags")
    return ClassifiedTags(_source_defaults(tags, classified), tuple(issues))
