"""Associate assets from explicit references, curated folders and scoped names."""
from collections import defaultdict
from pathlib import PurePosixPath
import re
import unicodedata

from gamedb.launchbox.matching import title_key
from .images import link_image_checksums, link_launcher_media
from .source import PROJECTS, Location, local_path, pack_for_launcher


REFERENCES = {'ApplicationPath': 'launcher', 'ConfigurationPath': 'configuration',
              'ManualPath': 'manual', 'MusicPath': 'music', 'VideoPath': 'video',
              'ThemeVideoPath': 'theme_video', 'VideoUrl': 'video', 'MusicUrl': 'music',
              'WikipediaURL': 'reference'}
PLATFORM_MEDIA = {'platforms': 'Platform', 'playlists': 'Playlist',
                  'platform categories': 'PlatformCategory'}


def name_key(value):
    return re.sub(r'[<>:"/\\|?*]', '_', unicodedata.normalize('NFC', value)).strip().casefold()


class Associations:
    def __init__(self, inventory):
        self.inv = inventory
        self.by_number = {a.number: a for a in inventory.assets.values()}
        self.folded = defaultdict(list)
        self.names = defaultdict(set)
        self.normal_names = defaultdict(set)
        self.roots = defaultdict(set)
        self.packages = defaultdict(set)
        self.platform_records = {}
        self.explicit = set()
        for a in inventory.assets.values():
            self.folded[a.path.casefold()].append(a)

    def add(self, owner, asset, role, basis, label):
        self.inv.links.add((owner, asset, role, basis, label))

    def reference(self, game, field, value, role, label):
        if value.lower().startswith(('https://', 'http://')):
            if value not in self.inv.assets:
                asset = self.inv.asset(value, 'url')
                self.inv.locations.append((asset.number, Location(value, 0, None, None, None, None)))
            asset = self.inv.assets[value]
        elif field.lower().endswith('url'):
            self.inv.issue('invalid_url', f'{field}={value}', game)
            return
        else:
            path = local_path(value)
            asset = self.inv.assets.get(path)
            if asset is None:
                candidates = self.folded.get(path.casefold(), ()) if path else ()
                if len(candidates) != 1:
                    self.inv.issue('ambiguous_reference' if candidates else 'missing_reference',
                                   f'{field}={value}', game, candidates=[a.number for a in candidates])
                    return
                asset = candidates[0]
        self.add(game, asset.number, role, field, label)
        self.explicit.add(asset.number)

    def add_name(self, game, value):
        if value:
            self.names[(game.platform, name_key(value))].add(game.number)
            self.normal_names[(game.platform, title_key(value))].add(game.number)

    def records(self):
        seen = set()
        for r in self.inv.records:
            if r.kind in ('Playlist', 'Platform', 'PlatformCategory') and r.label:
                self.platform_records.setdefault((r.kind, r.label.casefold()), r.number)
            game = self.inv.games.get((r.platform, (r.game_id or '').casefold()))
            if game is None:
                continue
            if r.kind == 'AlternateName':
                self.add_name(game, r.label)
            if r.kind not in ('Game', 'AdditionalApplication'):
                continue
            # Overlapping XML lists often repeat identical references.
            key = (game.number, r.kind, r.label, *(r.fields.get(k) for k in (*REFERENCES, 'RootFolder')))
            if key in seen:
                continue
            seen.add(key)
            app = local_path(r.fields.get('ApplicationPath') or '')
            if r.kind == 'Game':
                self.add_name(game, r.label)
                if app:
                    self.add_name(game, PurePosixPath(app).stem)
                folder = local_path(r.fields.get('RootFolder') or '')
                if not folder and app and '/' in app:
                    folder = app.rsplit('/', 1)[0]
                if folder:
                    self.roots[folder.casefold()].add(game.number)
            if app:
                package = pack_for_launcher(app)
                if package:
                    self.packages[package.casefold()].add(game.number)
                    if r.kind == 'Game' and not self.folded.get(package.casefold()):
                        self.inv.issue('missing_game_package', package, game.number)
            for field, role in REFERENCES.items():
                value = r.fields.get(field)
                if value:
                    if r.kind == 'AdditionalApplication' and field == 'ApplicationPath':
                        role = 'additional_application'
                    label = value.replace('\\', '/').rsplit('/', 1)[-1]
                    if role == 'additional_application' and r.label:
                        label = r.label
                    self.reference(game.number, field, value, role, label)

    def associate(self, owners, asset, role, basis):
        if len(owners) > 1:
            self.inv.issue('ambiguous_' + basis, asset.path, asset=asset.number, candidates=owners)
        elif owners:
            self.add(next(iter(owners)), asset.number, role, basis, PurePosixPath(asset.path).name)

    def pack_members(self):
        media_owners = {}
        for path, asset in self.inv.assets.items():
            if asset.kind != 'media_pack':
                continue
            p = PurePosixPath(path)
            if len(p.parts) >= 4 and p.parts[1].casefold() == 'gamedata':
                package = '/'.join(('eXo', *p.parts[2:]))
                owners = self.packages.get(package.casefold(), ())
                self.associate(owners, asset, 'media_pack', 'companion_pack')
                if len(owners) == 1:
                    media_owners[path] = next(iter(owners))
        for asset_no, location in self.inv.locations:
            owner = media_owners.get(location.path)
            if owner and location.member_no:
                a = self.by_number[asset_no]
                self.add(owner, asset_no, a.kind, 'companion_pack_member', PurePosixPath(a.path).name)
                self.explicit.add(asset_no)

    def link_path(self, asset):
        p = PurePosixPath(asset.path)
        parts = p.parts
        if asset.kind == 'collection_document':
            for platform, project in PROJECTS.items():
                if project.casefold() in p.name.casefold() or platform.casefold() in p.name.casefold():
                    owner = self.platform_records.get(('Platform', platform.casefold()))
                    if owner:
                        self.add(owner, asset.number, asset.kind, 'collection_name', p.name)
            return
        if asset.kind == 'game_package':
            owners = self.packages.get(asset.path.casefold(), ())
            self.associate(owners, asset, 'game_package', 'launcher_package')
            if not owners:
                self.inv.issue('unassigned_game_package', asset.path, asset=asset.number)
            return
        if parts[0].casefold() == 'exo' and len(parts) > 3 and parts[2].startswith('!'):
            for i in range(4, len(parts)):
                owners = self.roots.get('/'.join(parts[:i]).casefold(), ())
                if owners:
                    self.associate(owners, asset, asset.kind, 'game_folder')
                    return
        if asset.kind not in ('manual', 'music', 'video', 'artwork') or len(parts) < 3:
            return
        category = PLATFORM_MEDIA.get(parts[1].casefold())
        if category:
            label = parts[2] if len(parts) > 3 else p.stem
            owner = self.platform_records.get((category, label.casefold()))
            if owner:
                self.add(owner, asset.number, asset.kind, 'collection_folder', p.name)
            return
        if asset.number in self.explicit or parts[1] not in PROJECTS:
            return
        # LaunchBox adds an image slot suffix. Try the literal name first so
        # titles ending in digits retain their meaning.
        stems = [p.stem]
        if asset.kind == 'artwork' and re.search(r'-\d{2,3}$', p.stem):
            stems.append(p.stem.rsplit('-', 1)[0])
        for index, normalize in ((self.names, name_key), (self.normal_names, title_key)):
            for stem in stems:
                owners = index.get((parts[1], normalize(stem)), ())
                if owners:
                    self.associate(owners, asset, asset.kind, 'platform_name')
                    return


def link_assets(inventory, root, jobs, digest, progress):
    matches = Associations(inventory)
    matches.records()
    matches.pack_members()
    link_launcher_media(matches)
    link_image_checksums(matches, root, jobs, digest, progress)
    for asset in inventory.assets.values():
        matches.link_path(asset)
