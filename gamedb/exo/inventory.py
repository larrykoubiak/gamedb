"""Preserve source records, logical installation paths and physical locations."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from . import source


@dataclass(slots=True)
class Record:
    number: int
    document: str
    row: int
    kind: str
    platform: str | None
    source_id: str | None
    game_id: str | None
    label: str | None
    fields: dict


@dataclass(slots=True)
class Asset:
    number: int
    path: str
    kind: str
    category: str | None
    region: str | None


def asset_kind(path):
    p = PurePosixPath(path)
    parts = p.parts
    lower = tuple(x.casefold() for x in parts)
    top = lower[0]
    if source.is_game_package(path):
        return 'game_package', None, None
    if source.is_media_pack(path):
        return 'media_pack', None, None
    if 'extras' in lower or (top == 'exo' and 'magazines' in lower):
        suffix = p.suffix.casefold()
        category = 'launcher' if suffix in source.SCRIPT_SUFFIXES else suffix.lstrip('.') or None
        return 'extra', category, None
    if top == 'images':
        if len(parts) > 1 and lower[1] in ('cache-lb', 'cache-bb'):
            return 'launcher_preview', parts[1], None
        if len(parts) >= 5 and lower[1] in ('platforms', 'playlists', 'platform categories'):
            return 'artwork', parts[3], None
        return 'artwork', parts[2] if len(parts) > 3 else None, parts[3] if len(parts) == 5 else None
    if top in ('manuals', 'music', 'videos'):
        return {'manuals': 'manual', 'music': 'music', 'videos': 'video'}[top], None, None
    if source.document_kind(path):
        return 'metadata', None, None
    if p.suffix.casefold() in source.SCRIPT_SUFFIXES:
        return 'script', None, None
    if p.suffix.casefold() in ('.cfg', '.conf', '.ini'):
        return 'configuration', None, None
    if len(parts) == 1 and p.suffix.casefold() in ('.pdf', '.txt'):
        return 'collection_document', None, None
    return 'file', None, None


class Inventory:
    def __init__(self):
        self.documents = {}
        self.records = []
        self.games = {}
        self.assets = {}
        self.locations = []
        self.links = set()
        self.issues = set()
        self.image_evidence = []
        self.revision = ''

    def asset(self, path, kind=None):
        existing = self.assets.get(path)
        if existing is None:
            category, region = None, None
            if kind is None:
                kind, category, region = asset_kind(path)
            existing = Asset(len(self.assets) + 1, path, kind, category, region)
            self.assets[path] = existing
        return existing

    def issue(self, kind, reference, record=None, asset=None, candidates=()):
        self.issues.add((kind, reference, record, asset, tuple(sorted(candidates))))

    def read_documents(self, root, files):
        unique_content = {}
        priority = {'all': 0, 'active': 1, 'assembled': 2, 'family': 3}
        seen = set()
        for path in sorted(files, key=lambda p: (priority.get(source.document_kind(p), 4), p)):
            kind = source.document_kind(path)
            if not kind:
                continue
            data = (root / path).read_bytes()
            digest = sha256(data).hexdigest()
            self.documents[path] = (kind, digest, unique_content.setdefault(digest, data))
            if kind == 'index':
                continue
            platform = source.platform_list(path)
            for row, (tag, fields) in enumerate(source.xml_rows(path, data), 1):
                game_id = fields.get('GameID') or fields.get('GameId')
                source_id = fields.get('ID') or fields.get('Id') or fields.get('PlaylistId')
                if tag == 'Game':
                    game_id = source_id
                    if not game_id or not fields.get('Title') or not (fields.get('Platform') or platform):
                        raise ValueError(f'{path} row {row}: incomplete Game identity')
                label = fields.get('Title') or fields.get('Name') or fields.get('GameTitle')
                list_name = fields.get('Platform') or platform or fields.get('GamePlatform')
                record = Record(len(self.records) + 1, path, row, tag, list_name,
                                source_id, game_id, label, fields)
                self.records.append(record)
                if tag == 'Game':
                    key = (list_name, game_id.casefold())
                    if (path, key) in seen:
                        self.issue('duplicate_game_id', game_id, record.number)
                    seen.add((path, key))
                    self.games.setdefault(key, record)
        if not self.games:
            raise ValueError('No eXo game manifests found at the source root')

    def counts(self):
        primary = {r.number: r.platform for r in self.games.values()}
        covered = Counter()
        matched = set()
        owners = set()
        for owner, asset, role, _, _ in self.links:
            owners.add(asset)
            if role == 'game_package' and owner in primary and (owner, asset) not in matched:
                covered[primary[owner]] += 1
                matched.add((owner, asset))
        kinds = Counter(a.kind for a in self.assets.values())
        return {
            'documents': len(self.documents), 'records': len(self.records),
            'source_games_and_setup_entries': len(primary), 'assets': len(self.assets),
            'locations': len(self.locations), 'links': len(self.links),
            'image_checksum_evidence': len(self.image_evidence),
            'game_packages': kinds['game_package'], 'game_package_links_by_list': dict(covered),
            'assets_by_kind': dict(kinds),
            'unlinked_by_kind': dict(Counter(a.kind for a in self.assets.values() if a.number not in owners)),
            'issues_by_kind': dict(Counter(i[0] for i in self.issues)),
        }

    def compare_locations(self):
        """A logical path is an installation slot. Preserve differing copies."""
        first_size = {}
        first_crc = {}
        conflicts = set()
        for asset_no, location in self.locations:
            if location.size is not None and first_size.setdefault(asset_no, location.size) != location.size:
                conflicts.add(asset_no)
            if location.crc32 and first_crc.setdefault(asset_no, location.crc32) != location.crc32:
                conflicts.add(asset_no)
        for asset in self.assets.values():
            if asset.number in conflicts:
                self.issue('different_copies', asset.path, asset=asset.number)


def scan(root, jobs=8, progress=lambda msg: None):
    from .links import link_assets

    root = Path(root).resolve(strict=True)
    inventory = Inventory()
    progress('Listing source files')
    files = source.files_on_disk(root)
    signature = source.file_revision(files)
    progress(f'Reading manifests and indexes from {len(files):,} files')
    inventory.read_documents(root, files)
    if not any(source.is_game_package(p) for p in files):
        raise ValueError('No game packages found at the source root')
    digest = sha256(b'gamedb-exo-staging-v1\n')
    source.fingerprint(digest, signature)
    for path, (_, checksum, _) in sorted(inventory.documents.items()):
        source.fingerprint(digest, (path, checksum))
    for path, (size, mtime) in sorted(files.items()):
        entry = inventory.asset(path)
        inventory.locations.append((entry.number, source.Location(path, 0, None, size, None, mtime)))
    progress('Reading ZIP directories for metadata and per-game media packs')
    for count, (pack, members) in enumerate(source.archive_lists(root, files, jobs), 1):
        for path, location in members:
            source.fingerprint(digest, (pack, location.member_no, location.member_name, location.size, location.crc32))
            if path is None:
                inventory.issue('invalid_archive_path', f'{pack}#{location.member_no} {location.member_name}')
                continue
            entry = inventory.asset(path)
            inventory.locations.append((entry.number, location))
        if count % 1000 == 0:
            progress(f'Read {count:,} media packs')
    progress('Linking source records to assets')
    link_assets(inventory, root, jobs, digest, progress)
    inventory.compare_locations()
    # Corrected launcher interpretation can change independently of the
    # preserved files. Keep those revisions distinct on a later reimport.
    for asset in inventory.assets.values():
        source.fingerprint(digest, ('asset', asset.path, asset.kind, asset.category, asset.region))
    for link in sorted(inventory.links):
        source.fingerprint(digest, ('link', *link))
    for issue in sorted(inventory.issues, key=repr):
        source.fingerprint(digest, ('issue', *issue))
    progress('Verifying the source inventory')
    if signature != source.file_revision(source.files_on_disk(root)):
        raise ValueError('The eXo inventory changed during the scan. Retry when the source is stable.')
    inventory.revision = digest.hexdigest()
    return inventory
