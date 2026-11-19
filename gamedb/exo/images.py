"""Keep displayed media associations and checksum attributions as separate evidence."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from html import unescape
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from zlib import crc32

from .source import PROJECTS, fingerprint


GUID = re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', re.I)


def display_key(name):
    # eXoGUI 1.1.11 mapGamesMedia/loadPlatformImages use this spelling.
    return re.sub(r"""[:;?'"/\\]""", '_', name).strip().upper()


def file_crc(job):
    root, asset_no, loc = job
    checksum = 0
    with (root / loc.path).open('rb') as stream:
        for block in iter(lambda: stream.read(512 * 1024), b''):
            checksum = crc32(block, checksum)
    return asset_no, loc, checksum


@contextmanager
def image_db(path):
    # A running LaunchBox may have uncheckpointed rows. SQLite can replay a
    # copied journal without acquiring locks or writing to the source share.
    journals = [Path(str(path) + suffix) for suffix in ('-wal', '-journal')]
    journals = [j for j in journals if j.is_file() and j.stat().st_size]
    if journals:
        with TemporaryDirectory() as tmp:
            copy = Path(tmp) / path.name
            for item in [path, *journals]:
                shutil.copyfile(item, copy.parent / item.name)
            with closing(sqlite3.connect(copy)) as db:
                yield db
    else:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            yield db


def link_launcher_media(matches):
    inv = matches.inv
    platform_guids = {(r.platform, r.game_id.lower()): r.number for r in inv.games.values()}
    guids = defaultdict(set)
    for (_, guid), owner in platform_guids.items():
        guids[guid].add(owner)
    # eXoGUI builds a per-platform index of loose original images by image
    # category. A game looks up its Title, then Title.ID if that group is absent.
    grouped = defaultdict(list)
    categories = defaultdict(set)
    primary_titles = defaultdict(set)
    for game in inv.games.values():
        primary_titles[game.platform, display_key(unescape(game.label))].add(game.number)
    physical = {no for no, loc in inv.locations if loc.member_no == 0 and loc.size is not None}
    for a in inv.assets.values():
        p = PurePosixPath(a.path)
        guid = GUID.search(p.name)
        if a.kind == 'launcher_preview' and guid:
            owners = guids.get(guid[0].lower(), ())
            matches.associate(owners, a, 'launcher_preview', 'launchbox_cache_guid')
            continue
        if a.kind != 'artwork' or len(p.parts) < 4 or p.parts[1] not in PROJECTS:
            continue
        platform, category = p.parts[1:3]
        if guid:
            owner = platform_guids.get((platform, guid[0].lower()))
            if owner:
                matches.add(owner, a.number, 'artwork', 'launchbox_filename_guid', p.name)
                matches.explicit.add(a.number)
        # LaunchBox also numbers image slots 10 and above. Alternate game
        # names are not equal to a primary local title for these filenames.
        numbered = re.fullmatch(r'(.+)-\d{2,}', p.stem)
        if numbered and not guid:
            for owner in primary_titles.get((platform, display_key(numbered[1])), ()):
                matches.add(owner, a.number, 'artwork', 'launchbox_title', p.name)
                matches.explicit.add(a.number)
        end = p.name.rfind('-0')
        if end >= 0 and a.number in physical:
            grouped[platform, category, display_key(p.name[:end])].append(a)
            categories[platform].add(category)

    # The active manifest can contain an edited title. Preserve the full-list
    # naming rule separately for games that are only in the distribution.
    active = {(r.platform, r.game_id.lower()): r for r in inv.records
              if r.kind == 'Game' and r.document.startswith('Data/Platforms/')}
    for key, primary in inv.games.items():
        r = active.get(key, primary)
        title = unescape(r.label).replace('\xa0', ' ')
        for category in categories[r.platform]:
            assets = grouped.get((r.platform, category, display_key(title)))
            if assets:
                basis = 'exogui_title'
            else:
                assets = grouped.get((r.platform, category, display_key(f'{title}.{r.game_id}')), ())
                basis = 'exogui_title_guid'
            for a in assets:
                matches.add(primary.number, a.number, 'artwork', basis, PurePosixPath(a.path).name)
                matches.explicit.add(a.number)
        app = r.fields.get('ApplicationPath', '').replace('\\', '/')
        video = 'Videos/' + r.platform + '/' + app.rsplit('/', 1)[-1].split('.')[0] + '.mp4'
        a = inv.assets.get(video)
        if a and a.number in physical:
            matches.add(primary.number, a.number, 'video', 'exogui_launcher_filename', PurePosixPath(video).name)
            matches.explicit.add(a.number)


def link_image_checksums(matches, root, jobs, digest, progress):
    inv = matches.inv
    originals = {a.number: a for a in inv.assets.values() if a.kind == 'artwork'
                 and len(PurePosixPath(a.path).parts) >= 4 and PurePosixPath(a.path).parts[1] in PROJECTS}
    by_crc = defaultdict(set)
    loose = []
    for number, loc in inv.locations:
        if number in originals:
            if loc.member_no:
                by_crc[int(loc.crc32, 16)].add(number)
            else:
                loose.append((root, number, loc))
    progress(f'Checking {len(loose):,} original artwork files against the LaunchBox image indexes')
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for number, loc, checksum in pool.map(file_crc, loose):
            loc.crc32 = f'{checksum:08x}'
            by_crc[checksum].add(number)
            fingerprint(digest, (loc.path, loc.crc32))

    db_games = defaultdict(set)
    for r in inv.records:
        dbid = r.fields.get('DatabaseID', '')
        if r.kind == 'Game' and dbid.isdecimal():
            owner = inv.games[(r.platform, r.game_id.casefold())]
            db_games[int(dbid), r.platform].add(owner.number)
    local_owners = defaultdict(set)
    for owner, number, role, _, _ in inv.links:
        if role == 'artwork':
            local_owners[number].add(owner)
    checksum_owners = defaultdict(set)
    for name in ('Metadata/LaunchBox.Metadata.db', 'Metadata/Metadata.db'):
        if name not in inv.assets:
            continue
        progress('Reading ' + name)
        with image_db(root / name) as db:
            rows = db.execute('SELECT FileName, DatabaseId, Type, Region, CRC32 FROM GameImages')
            for filename, dbid, kind, region, checksum in rows:
                if checksum is None:
                    continue
                crc = int(checksum) & 0xffffffff
                for number in by_crc.get(crc, ()):
                    a = originals[number]
                    platform = PurePosixPath(a.path).parts[1]
                    owners = db_games.get((dbid, platform))
                    if not owners or kind != a.category:
                        continue
                    inv.image_evidence.append((number, name, filename, dbid, kind, region, f'{crc:08x}'))
                    checksum_owners[number].update(owners)
    for number, owners in checksum_owners.items():
        a = originals[number]
        # The bundled XML sometimes assigns the same public DatabaseID to
        # unrelated local games. Local frontend bindings decide ownership.
        if local_owners[number]:
            corroborated = owners & local_owners[number]
            if not corroborated:
                inv.issue('image_index_disagrees', a.path, asset=number, candidates=owners)
            owners = corroborated
        elif len(owners) > 1:
            inv.issue('ambiguous_checksum_owner', a.path, asset=number, candidates=owners)
            owners = ()
        for owner in owners:
            matches.add(owner, number, 'artwork', 'launchbox_image_crc', PurePosixPath(a.path).name)
        matches.explicit.add(number)
    for row in sorted(inv.image_evidence):
        fingerprint(digest, row)
