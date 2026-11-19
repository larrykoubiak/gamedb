"""Interpret the same game directories, menu files and platform hints eXo launches."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import PurePosixPath
from zipfile import ZipFile

PC = ("IBM", "PC Compatibles")
# Original platform spellings from eXo's platform.txt files and edition labels.
PLATFORMS = (
    (("dos", "ms-dos"), PC, "MS-DOS"),
    (("windows", "win"), PC, "Windows"),
    (("pc",), PC, "PC"),
    (("mac", "macintosh", "mac os", "macos"), ("Apple", "Macintosh"), "Macintosh"),
    (("ios",), None, "iOS"),
    (("amiga",), ("Commodore", "Amiga"), "Amiga"),
    (("amiga cd32", "cd32"), ("Commodore", "Amiga CD32"), "Amiga CD32"),
    (("c64", "commodore 64"), ("Commodore", "C64"), "Commodore 64"),
    (("atari st", "st"), ("Atari", "ST"), "Atari ST"),
    (("apple ii", "apple2"), ("Apple", "II"), "Apple II"),
    (("apple iigs", "apple ii gs", "2gs"), ("Apple", "IIGS"), "Apple IIGS"),
    (("fmtowns", "fm towns", "towns"), ("Fujitsu", "FM Towns"), "FM Towns"),
    (("pc98", "pc-98"), None, "PC-98"),
    (("pc-9801",), ("NEC", "PC-9801"), "PC-9801"),
    (("pc-9821",), ("NEC", "PC-9821"), "PC-9821"),
    (("bbc", "bbc micro"), ("Acorn", "BBC"), "BBC Micro"),
    (("cpc", "amstrad cpc"), ("Amstrad", "CPC"), "Amstrad CPC"),
    (
        ("spectrum", "zx spectrum", "sp48", "s48"),
        ("Sinclair", "ZX Spectrum"),
        "ZX Spectrum",
    ),
    (("3do",), ("The 3DO Company", "3DO Interactive Multiplayer"), "3DO"),
    (("playstation", "psx"), ("Sony", "PlayStation"), "PlayStation"),
    (("ps2", "playstation 2"), ("Sony", "PlayStation 2"), "PlayStation 2"),
    (("nes",), ("Nintendo", "Nintendo Entertainment System"), "NES"),
    (("segacd", "sega cd", "mega-cd"), ("Sega", "Mega-CD"), "Sega CD"),
    (("linux",), None, "Linux"),
    (("xbox",), None, "Xbox"),
    (("dragon",), ("Dragon Data", "Dragon"), "Dragon"),
)
PLATFORM_CODES = {
    code: (system, label) for codes, system, label in PLATFORMS for code in codes
}
PLATFORM_PATTERN = re.compile(
    r"(?<![\w-])("
    + "|".join(re.escape(k) for k in sorted(PLATFORM_CODES, key=len, reverse=True))
    + r")(?![\w-])",
    re.IGNORECASE,
)
SUFFIX = re.compile(r"\(([^()]*)\)\s*$")
BOOT = re.compile(
    rb"(?im)^\s*@?boot\s+(?:-l\s+[ac]\b|[^\r\n]+\.(?:img|ima|jrc|dsk|booter)\b)"
)


def key(*parts):
    return sha256("\x1f".join(parts).encode()).hexdigest()


@dataclass(frozen=True)
class Edition:
    selection: str
    label: str
    environment: str
    system: tuple[str, str] | None
    evidence: str
    engine_game: str = ""
    runner_version: str = ""
    work_variant: str = ""
    runner: str | None = None


def runtime_index(content):
    index = {}
    for line in content.decode("cp1252").splitlines():
        parts = [item.strip() for item in line.split(";")]
        if len(parts) == 3 and parts[0] and parts[1]:
            index[parts[0].casefold()] = tuple(parts[1:])
    return index


def platform(marker, *names):
    if marker in PLATFORM_CODES:
        system, environment = PLATFORM_CODES[marker]
        return system, environment, "platform.txt"
    for name in names:
        suffix = SUFFIX.search(name)
        if suffix and (m := PLATFORM_PATTERN.search(suffix[1])):
            system, environment = PLATFORM_CODES[m[0].lower()]
            return system, environment, "edition label"
    return None, marker or "Unspecified", "platform.txt" if marker else "unresolved"


def scumm_editions(path, index):
    """Read ZIP directories and the small selector files, without extracting game data."""
    with ZipFile(path) as archive:
        children, controls = {}, {}
        for info in archive.infolist():
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if not parts or ".." in parts or parts[0] == "/":
                raise ValueError(f"Invalid game directory in {path.name}")
            for n in range(1, len(parts) if not info.is_dir() else len(parts) + 1):
                children.setdefault(parts[: n - 1], set()).add(parts[n - 1])
            if not info.is_dir() and parts[-1].casefold() in (
                "menu.txt",
                "platform.txt",
            ):
                if parts[-1].casefold() == "platform.txt" and info.file_size > 256:
                    raise ValueError(f"Invalid platform hint in {path.name}")
                controls[parts[:-1], parts[-1].casefold()] = info
        roots = sorted(children.get((), ()))
        if len(roots) != 1:
            raise ValueError(f"Expected one game directory in {path.name}: {roots}")
        root = roots[0]
        base_runner = index.get(
            root.casefold(), index.get(path.stem.casefold(), ("", ""))
        )
        choices = []

        def choose(parts, runner):
            runner = index.get(parts[-1].casefold(), runner)
            dirs = sorted(children.get(parts, ()))
            if dirs and (
                len(parts) == 1
                or (parts, "menu.txt") in controls
                or parts[-1].casefold() == "other languages"
            ):
                for name in dirs:
                    choose((*parts, name), runner)
                return
            marker = controls.get((parts, "platform.txt"))
            value = (
                archive.read(marker).decode("utf-8-sig").strip().lower()
                if marker
                else ""
            )
            system, env, basis = platform(value, *reversed(parts))
            choices.append(
                Edition(
                    "/".join(parts[1:]),
                    parts[-1],
                    env,
                    system,
                    basis,
                    *runner,
                    runner="ScummVM",
                )
            )

        choose((root,), base_runner)
        if len({choice.engine_game for choice in choices if choice.engine_game}) > 1:
            choices = [
                replace(choice, work_variant=choice.engine_game or choice.selection)
                for choice in choices
            ]
        return choices


def source_editions(root, game, index, dos_runners):
    package = root / game["package"]
    stat = package.stat()
    if (
        stat.st_size != game["package_size"]
        or stat.st_mtime_ns != game["package_mtime"]
    ):
        raise ValueError(f"Game package changed since staging: {game['package']}")
    if game["platform"].startswith("ScummVM"):
        return scumm_editions(package, index)
    if game["platform"] == "Windows 9x":
        script = root / game["launcher_path"]
        stat = script.stat()
        if (
            stat.st_size != game["launcher_size"]
            or stat.st_mtime_ns != game["launcher_mtime"]
        ):
            raise ValueError(f"Launcher changed since staging: {script.name}")
        launchers = set(
            re.findall(
                rb'(?im)^\s*(?:call\s+)?"?\.\\util\\9xlaunch(\w*)\.bat\b',
                script.read_bytes(),
            )
        )
        runtime = []
        for launcher in sorted(launchers):
            tag = launcher.lower()
            if not tag:
                runtime.append("DOSBox-X")
            elif tag.startswith(b"86box"):
                runtime.append("86Box")
            elif tag.startswith(b"pcbox"):
                runtime.append("PCBox")
        return [
            Edition(
                "",
                game["label"],
                "Windows 9x",
                PC,
                "eXo Windows 9x collection",
                runner=" / ".join(dict.fromkeys(runtime)) or None,
            )
        ]
    version = dos_runners.get(package.stem.casefold(), "")
    runner = "DOSBox" if version else None
    cfg = game["config_path"]
    if cfg:
        path = root / cfg
        stat = path.stat()
        if (
            stat.st_size != game["config_size"]
            or stat.st_mtime_ns != game["config_mtime"]
        ):
            raise ValueError(f"Game configuration changed since staging: {cfg}")
        if BOOT.search(path.read_bytes()):
            return [
                Edition(
                    "",
                    game["label"],
                    "PC booter",
                    PC,
                    "DOSBox boot command",
                    runner_version=version,
                    runner=runner,
                )
            ]
    return [
        Edition(
            "",
            game["label"],
            "MS-DOS",
            PC,
            "eXo MS-DOS collection",
            runner_version=version,
            runner=runner,
        )
    ]
