"""Inventory the curated installation and its distribution media in place."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
from xml.etree.ElementTree import iterparse
from zipfile import ZipFile


PROJECTS = {'MS-DOS': 'eXoDOS', 'ScummVM': 'eXoScummVM',
            'ScummVM SVN': 'eXoScummVM', 'Windows 9x': 'eXoWin9x'}
PROJECT_DIRS = {p.casefold() for p in PROJECTS.values()}
INDEXES = {'dosbox.txt', 'dosbox_linux.txt', 'scummvm.txt', 'scummvm.ini'}
MEDIA_ROOTS = {'images', 'manuals', 'videos', 'music', 'games', 'content', 'xml'}
MEDIA_SUFFIXES = {'.pdf', '.txt', '.rtf', '.epub', '.jpg', '.png', '.mp3', '.mp4'}
SCRIPT_SUFFIXES = {'.bat', '.command', '.bsh', '.msh', '.sh'}


def local_path(value):
    """Preserve spelling and reject paths that cannot identify a library member."""
    parts = value.replace('\\', '/').split('/')
    if not parts[0] or '..' in parts or ':' in parts[0] or '\0' in value:
        return None
    return '/'.join(p for p in parts if p not in ('', '.')) or None


def included(path, is_dir):
    parts = path.casefold().split('/')
    top = parts[0]
    if len(parts) == 1:
        if is_dir:
            return top in MEDIA_ROOTS | {'exo', 'data', 'metadata'}
        return PurePosixPath(path).suffix.lower() in MEDIA_SUFFIXES | SCRIPT_SUFFIXES
    if top == 'images':
        return True
    if top == 'metadata':
        return len(parts) == 2 and any(parts[1] == name + suffix
            for name in ('launchbox.metadata.db', 'metadata.db') for suffix in ('', '-wal', '-journal'))
    if top == 'data':
        return parts[1] in ('platforms', 'playlists', 'platforms.xml', 'parents.xml')
    if top == 'exo' and parts[1] in PROJECT_DIRS and len(parts) >= 3:
        # Installed, writable game trees can sit beside the preserved packages.
        if parts[2].startswith('!'):
            return True
        if parts[1] == 'exowin9x':
            return parts[2].isdecimal() and (len(parts) == 3 or (len(parts) == 4 and not is_dir))
        return len(parts) == 3 and not is_dir
    return top in MEDIA_ROOTS or top == 'exo'


def files_on_disk(root):
    found = {}

    def visit(directory, prefix):
        with os.scandir(directory) as entries:
            for item in entries:
                name = prefix + item.name
                if item.is_symlink():
                    continue
                directory_entry = item.is_dir(follow_symlinks=False)
                if not included(name, directory_entry):
                    continue
                if directory_entry:
                    visit(item.path, name + '/')
                elif item.is_file(follow_symlinks=False):
                    stat = item.stat(follow_symlinks=False)
                    found[name] = (stat.st_size, stat.st_mtime_ns)
    visit(root, '')
    return found


def document_kind(path):
    name = PurePosixPath(path)
    parts = name.parts
    if len(parts) == 3 and parts[:2] == ('eXo', 'util') and name.name in INDEXES:
        return 'index'
    if parts[0] == 'xml' and name.suffix.lower() in ('.xml', '.9x', '.platforms', '.parent'):
        return parts[1].lower() if len(parts) > 2 else 'assembled'
    if parts[0] == 'Data' and name.suffix.lower() == '.xml':
        return 'active'
    return None


def platform_list(path):
    name = PurePosixPath(path)
    if name.parts[:-1] in (('Data', 'Platforms'), ('xml', 'all'), ('xml', 'family')):
        if name.suffix.lower() == '.9x':
            return 'Windows 9x'
        return name.stem
    if path == 'xml/Windows 9x.xml':
        return 'Windows 9x'
    return None


def xml_rows(path, data):
    if PurePosixPath(path).suffix.lower() in ('.9x', '.platforms', '.parent'):
        data = b'<LaunchBox>' + data + b'</LaunchBox>'
    events = iterparse(BytesIO(data), events=('start', 'end'))
    _, root = next(events)
    if root.tag != 'LaunchBox':
        raise ValueError(f'{path}: expected LaunchBox XML, found {root.tag}')
    depth = 1
    for event, element in events:
        if event == 'start':
            depth += 1
        else:
            if depth == 2:
                yield element.tag, {c.tag: c.text for c in element if c.text}
                root.remove(element)
            depth -= 1


def pack_for_launcher(path):
    p = PurePosixPath(path)
    parts = p.parts
    if len(parts) < 5 or parts[0].lower() != 'exo' or not parts[2].startswith('!'):
        return None
    project = parts[1]
    if project.casefold() not in PROJECT_DIRS:
        return None
    folder = PurePosixPath(parts[0], project)
    if project.casefold() == 'exowin9x':
        folder /= parts[3]
    return str(folder / (p.stem + '.zip'))


def is_game_package(path):
    p = PurePosixPath(path)
    parts = p.parts
    if p.suffix.casefold() != '.zip' or len(parts) < 3 or parts[0].casefold() != 'exo':
        return False
    if parts[1].casefold() == 'exowin9x':
        return len(parts) == 4 and parts[2].isdecimal()
    return len(parts) == 3 and parts[1].casefold() in ('exodos', 'exoscummvm')


def is_media_pack(path):
    p = PurePosixPath(path)
    return (p.parts[0].casefold() == 'content' and p.suffix.casefold() == '.zip'
            and (len(p.parts) > 2 or 'metadata' in p.name.casefold()))


@dataclass(slots=True)
class Location:
    path: str
    member_no: int
    member_name: str | None
    size: int | None
    crc32: str | None
    mtime_ns: int | None


def packed_locations(job):
    root, relative = job
    with ZipFile(root / relative) as archive:
        return [
            (local_path(item.filename), Location(relative, n, item.filename, item.file_size,
                                                  f'{item.CRC:08x}', None))
            for n, item in enumerate(archive.infolist(), 1) if not item.is_dir()
        ]


def archive_lists(root, files, jobs):
    packs = sorted(p for p in files if is_media_pack(p))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        yield from zip(packs, pool.map(packed_locations, ((root, p) for p in packs)))


def fingerprint(digest, row):
    digest.update(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode())
    digest.update(b'\n')


def file_revision(files):
    digest = sha256()
    for path, (size, mtime) in sorted(files.items()):
        fingerprint(digest, (path, size, mtime))
    return digest.hexdigest()
