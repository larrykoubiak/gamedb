"""Cache source indexes used to enrich retail catalogs."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen


MAME = "https://github.com/mamedev/mame/blob/mame0285/hash/"
MAME_RAW = "https://raw.githubusercontent.com/mamedev/mame/mame0285/hash/"
ARES = "https://github.com/ares-emulator/ares/blob/v148/mia/Database/Super%20Famicom.bml"
SNES_CENTRAL = "https://snescentral.com/"
JENSMA = "https://www.jensma.de/snes/"
GAMING_ALEXANDRIA = "https://www.gamingalexandria.com/wp/scans/super-famicom/"
PEEBS = "https://sites.google.com/view/snesmanuals"
PEEBS_JP = "https://sites.google.com/view/superfamicommanuals"
PEEBS_ITEM = "snes_manual_archive"
KIRKLAND_ITEM = "kirklands_manual_labor_-_super_nintendo_-_usa_-_2k_version"
PEEBS_SHEETS = {
    "en": ("2PACX-1vTsChNHLjB0GMwztaZL9GDQvBU7anov2iBYXthd167iLS-dQQUxDNq0zrGkGoGGeBZRkgNnW3fsl-we", 500176394),
    "jp": ("2PACX-1vQyvhdDjE3vJLAeeMh0PMBVW6JltsOOTA6LLHTWoLGpzi59adnG_mhdWNNgFhHUPvEIfRIIlAA07Npy", 0),
}
THUMBNAILS = {
    "snes": ("Nintendo - Super Nintendo Entertainment System", "3298e21ecddfba90a589180f81ea242d2a90d7bb"),
    "sufami": ("Nintendo - Sufami Turbo", "35daf4f263c92c5b7aac182098d0de102f28c4ab"),
}
MAX_INDEX_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class SourceIndex:
    url: str
    content: bytes

    @property
    def digest(self):
        return sha256(self.content).hexdigest()


def read_index(path, url):
    if path.is_file():
        with path.open("rb") as stream:
            content = stream.read(MAX_INDEX_BYTES + 1)
    else:
        request = Request(url, headers={"User-Agent": "GameDB/2.0 (catalog metadata)"})
        with urlopen(request, timeout=20) as stream:
            content = stream.read(MAX_INDEX_BYTES + 1)
        if len(content) > MAX_INDEX_BYTES:
            raise ValueError(f"Catalog source is too large: {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(content)
                stream.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    if len(content) > MAX_INDEX_BYTES:
        raise ValueError(f"Catalog source is too large: {path.name}")
    return SourceIndex(url, content)


def reference_indexes(directory):
    """Read saved indexes first so reseeding can reuse the same evidence."""
    urls = {
        "mame.xml": MAME_RAW + "snes.xml",
        "mame-strom.xml": MAME_RAW + "snes_strom.xml",
        "ares-snes.bml": "https://raw.githubusercontent.com/ares-emulator/ares/v148/mia/Database/Super%20Famicom.bml",
        "peebs-archive.json": f"https://archive.org/metadata/{PEEBS_ITEM}",
        "kirkland-archive.json": f"https://archive.org/metadata/{KIRKLAND_ITEM}",
        "jensma-index.html": JENSMA,
    }
    for language, (sheet, tab) in PEEBS_SHEETS.items():
        urls[f"peebs-rows-{language}.html"] = (
            f"https://docs.google.com/spreadsheets/d/e/{sheet}/pubhtml/sheet?gid={tab}&single=true"
        )
    for name, (folder, revision) in THUMBNAILS.items():
        repository = folder.replace(" ", "_")
        urls[f"thumbs-{name}.json"] = (
            f"https://api.github.com/repos/libretro-thumbnails/{repository}/git/trees/{revision}?recursive=1"
        )

    indexes, warnings = {}, []
    for name, url in urls.items():
        try:
            indexes[name] = read_index(directory / name, url)
        except (OSError, ValueError) as error:
            warnings.append(f"{name}: {error}")
    return indexes, warnings


def snes_central_indexes(directory):
    """Use saved scan indexes and board pages with their original URLs."""
    for path in sorted(directory.glob("central-*-cart.html")):
        region = path.name.removeprefix("central-").removesuffix("-cart.html")
        if region.isalpha() and region.isupper():
            yield region, read_index(path, SNES_CENTRAL + f"scanlist.php?region={region}&type=cart")
    for path in sorted(directory.glob("central-pcb-*.html")):
        board = path.stem.removeprefix("central-pcb-")
        if all(c.isalnum() or c == "-" for c in board):
            yield board, read_index(path, SNES_CENTRAL + f"pcbboards.php?chip={board}")
