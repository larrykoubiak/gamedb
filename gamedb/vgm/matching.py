"""Find soundtrack owners from titles and evidence specific to the source format."""

import csv
import re
from collections import Counter, defaultdict

from gamedb.config import PROJECT_ROOT
from gamedb.exo.works import credit as publisher_key
from gamedb.launchbox.matching import title_key

from .inventory import PLAYSTATION, PSF_COLLECTION, SNES

REVIEWED_TITLES = PROJECT_ROOT / "reference/vgm_titles.csv"
EXTENDED_SYSTEMS = frozenset({PLAYSTATION, SNES})
ARTICLES = {"a", "an", "the"}
ROMAN_NUMERALS = dict(zip(
    ("ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii"),
    ("2", "3", "4", "6", "7", "8", "9", "11", "12"),
))
ACRONYM = re.compile(r"\b[A-Za-z](?:\.[A-Za-z])+\b")
MOVED_ARTICLE = re.compile(r"^(.+?),\s*(the|an|a)(?=\s*[-:])", re.IGNORECASE)
PARENTHETICAL_TITLE = re.compile(r"^(.+?)\s+\(([^()]+)\)$")
SID_CREDIT = re.compile(r"^\s*(?:©\s*|\(c\)\s*)?((?:19[7-9]|20)\d)\s+(.+)$", re.IGNORECASE)
YEAR = re.compile(r"^((?:19[7-9]|20)\d)(?:[-/]|$)")


def reviewed_titles(path=REVIEWED_TITLES):
    with path.open(newline="", encoding="utf-8") as handle:
        return {(row["collection"], row["source_name"]): row for row in csv.DictReader(handle)}


def spelling_key(value):
    """Keep the words of the title while allowing common typography and number variants."""
    value = MOVED_ARTICLE.sub(r"\2 \1", value)
    value = ACRONYM.sub(lambda match: match[0].replace(".", ""), value)
    value = value.replace("'", "").replace("’", "")
    return " ".join(ROMAN_NUMERALS.get(word, word)
                    for word in title_key(value.replace("&", " and ")).split())


def psf_album(item):
    """Use a consistent PSF1 game tag that preserves the long set name."""
    if item.collection != PSF_COLLECTION:
        return None
    names = Counter(asset["album"] for asset in item.assets
                    if asset["format"] in {"psf", "minipsf"} and asset.get("album"))
    if sum(names.values()) < 2 or len({spelling_key(name) for name in names}) != 1:
        return None
    name = names.most_common(1)[0][0]
    source = [word for word in spelling_key(item.title).split() if word not in ARTICLES]
    tagged = [word for word in spelling_key(name).split() if word not in ARTICLES]
    if source and source == tagged:
        return name
    # An embedded title can supply a subtitle. Require the full set title
    # and the same installment numbers, including for a later or trial edition.
    if (len(source) >= 2 and tagged[:len(source)] == source
            and not any(word.isdecimal() for word in tagged[len(source):])):
        return name
    return None


def snes_filename_titles(item):
    if item.collection == "spcsets":
        match = PARENTHETICAL_TITLE.fullmatch(item.title)
        if match:
            return match.groups()
    return ()


def without_article(value):
    words = title_key(value).split()
    if words and words[0] in ARTICLES:
        words = words[1:]
    return " ".join(words)


def sid_claim(item):
    """Read the game and release evidence from a SID with an agreeing filename."""
    for asset in item.assets:
        if asset["format"] != "sid" or not asset.get("album"):
            continue
        album = asset["album"]
        if not without_article(album) or without_article(album) != without_article(item.title):
            continue
        credit = SID_CREDIT.fullmatch(asset.get("copyright", ""))
        return {
            "album": album,
            "copyright": asset.get("copyright", ""),
            "year": credit[1] if credit else "",
            "publisher": publisher_key(credit[2]) if credit else "",
            "game_folder": asset["source_path"].startswith("C64Music/GAMES/"),
        }
    return None


class TitleIndex:
    """Index requested titles against canonical software and attributed aliases."""

    def __init__(self, names):
        self.exact = defaultdict(dict)
        self.spellings = defaultdict(dict)
        self.metadata = defaultdict(dict)
        self.names = {(platform, title_key(name)) for platform, name in names}
        self.spelled_names = {(platform, spelling_key(name)) for platform, name in names
                              if platform in EXTENDED_SYSTEMS}
        self.names = {key for key in self.names if key[1]}
        self.spelled_names = {key for key in self.spelled_names if key[1]}

    def add(self, platform, row, *, database_id=None):
        name = row["name"]
        exact_key = (platform, title_key(name))
        spelled_key = (platform, spelling_key(name)) if platform in EXTENDED_SYSTEMS else None
        if exact_key not in self.names and spelled_key not in self.spelled_names:
            return
        candidate = {
            "softwareId": row["id"], "title": row["display_name"], "target_key": row["target_key"],
            "matchedTitle": name,
        }
        if database_id is not None:
            if spelled_key in self.spelled_names:
                candidate["launchboxDatabaseId"] = database_id
                self.metadata[spelled_key].setdefault(row["id"], candidate)
        else:
            if exact_key in self.names:
                self.exact[exact_key].setdefault(row["id"], candidate)
            if spelled_key in self.spelled_names:
                self.spellings[spelled_key].setdefault(row["id"], candidate)

    def lookup(self, platform, names, *, catalog_only=False):
        """Prefer full catalog titles before using equivalent spellings and attributed aliases."""
        tiers = [(self.exact, title_key, "catalog_title")]
        if platform in EXTENDED_SYSTEMS:
            tiers.append((self.spellings, spelling_key, "catalog_spelling"))
            if not catalog_only:
                tiers.append((self.metadata, spelling_key, "launchbox_title"))
        for index, normalize, basis in tiers:
            hits = {}
            for name in names:
                for ident, row in index.get((platform, normalize(name)), {}).items():
                    hits.setdefault(ident, {**row, "sourceTitle": name, "titleBasis": basis})
            if hits:
                return hits
        return {}


def match_titles(index, item, reviewed, album, sid):
    if reviewed and reviewed["catalog_title"]:
        hits = index.lookup(item.system, (reviewed["catalog_title"],), catalog_only=True)
        return {ident: {**hit, "reviewNote": reviewed["evidence"]} for ident, hit in hits.items()}
    hits = index.lookup(item.system, (item.title, *item.aliases))
    parts = snes_filename_titles(item)
    if parts and not hits:
        left, right = (index.lookup(item.system, (part,)) for part in parts)
        if left and right:
            hits = {ident: {**hit, "snesFilenameTitles": list(parts)}
                    for ident, hit in (left | right).items()}
    if sid:
        # Retain both literal names if the filename omits a leading article.
        hits.update(index.lookup(item.system, (sid["album"],)))
    if album:
        for ident, hit in index.lookup(item.system, (album,)).items():
            hits.setdefault(ident, {**hit, "psfGameTag": album})
    return hits


def match_sid(hits, sid, credits):
    if not hits or not sid:
        return None, None
    credit = (sid["year"], sid["publisher"])
    has_credit = all(credit)
    supported = [ident for ident in hits if has_credit and credit in credits.get(ident, ())]
    if len(supported) == 1:
        return supported[0], "sid_year_and_publisher"
    if (sid["game_folder"] and len(hits) == 1
            and (not has_credit or not any(credits.get(ident) for ident in hits))):
        return next(iter(hits)), "hvsc_game_folder_and_sid_title"
    return None, None
