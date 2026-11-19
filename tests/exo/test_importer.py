from contextlib import closing, contextmanager
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from xml.etree.ElementTree import Element, SubElement, parse, tostring
from zipfile import ZipFile
from zlib import crc32

from sqlalchemy import func, select
from gamedb.database import create_database_engine
from gamedb.exo import schema
from gamedb.exo.inventory import scan
from gamedb.exo.importer import publish


DOOM = '11111111-1111-4111-a111-111111111111'
ULTIMATE = '22222222-2222-4222-a222-222222222222'


class ExoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cover = 'Images/MS-DOS/Box - Front/World/DOOM-01.jpg'
        self.weird = 'Images/MS-DOS/Box - Back/World/unrelated scan.jpg'
        self.preview = 'Images/Cache-LB/.Boxes-' + ULTIMATE + '-217-336.jpg'
        self.extra = 'eXo/eXoDOS/!dos/doomp/Extras/Reference Card.pdf'
        self.manual = 'Manuals/MS-DOS/DOOM (1993).pdf'
        self.pack = 'Content/GameData/eXoDOS/DOOM (1993).zip'
        for name, data in [(self.cover, b'cover'), (self.weird, b'back'), (self.preview, b'thumb'),
                           (self.manual, b'updated'), (self.extra, b'card')]:
            self.file(name, data)
        self.zip(self.pack, [(self.extra, b'card'), (self.manual, b'older copy'), ('../oops', b'bad')])

        rows = []
        for guid, title, dbid, folder, release in [
            (DOOM, 'DOOM', '745', 'doomp', 'DOOM (1993)'),
            (ULTIMATE, 'The Ultimate DOOM', '14119', 'ult', 'Ultimate DOOM (1995)'),
        ]:
            root_folder = f'eXo/eXoDOS/!dos/{folder}'
            app = f'{root_folder}/{release}.bat'
            self.file(app, b'launcher')
            self.zip('eXo/eXoDOS/' + release + '.zip', [('GAME.EXE', b'game')])
            fields = {'ID': guid, 'Platform': 'MS-DOS', 'Title': title, 'DatabaseID': dbid,
                      'RootFolder': root_folder, 'ApplicationPath': app}
            if guid == DOOM:
                fields.update(ManualPath=self.manual.lower(), VideoUrl='https://example.invalid/clip')
            rows.append(('Game', fields))
        rows.append(('AlternateName', {'GameID': ULTIMATE, 'Name': 'DOOM'}))
        self.xml('xml/all/MS-DOS.xml', rows)
        self.xml('Data/Platforms/MS-DOS.xml', rows)
        self.xml('xml/family/MS-DOS.xml', rows[1:2])
        win_app = 'eXo/eXoWin9x/!win9x/1996/DoomW/DoomW.bat'
        self.file(win_app, b'win')
        self.zip('eXo/eXoWin9x/1996/DoomW.zip', [('disk.vhd', b'x')])
        self.xml('xml/all/1994-1996.9x', [('Game', {'ID': DOOM, 'Title': 'DOOM', 'Platform': 'Windows 9x',
                                                    'ApplicationPath': win_app})], fragment=True)
        self.file('Images/MS-DOS/Disc/DOOM.' + DOOM + '-01.png', b'disc')
        p = self.root / 'Metadata/LaunchBox.Metadata.db'
        p.parent.mkdir()
        with closing(sqlite3.connect(p)) as db, db:
            db.execute('CREATE TABLE GameImages(FileName,DatabaseId,Type,Region,CRC32)')
            db.execute('INSERT INTO GameImages VALUES(?,?,?,?,?)',
                       ('remote-scan.jpg', 745, 'Box - Back', 'World', crc32(b'back')))

    def file(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def zip(self, name, members):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(p, 'w') as z:
            for path, data in members:
                z.writestr(path, data)

    def xml(self, path, rows, fragment=False):
        root = Element('LaunchBox')
        for tag, fields in rows:
            row = SubElement(root, tag)
            for k, value in fields.items():
                SubElement(row, k).text = value
        self.file(path, b''.join(tostring(row) for row in root) if fragment else tostring(root))

    def test_source_associations_pack_locations_and_scoped_ids(self):
        i = scan(self.root)
        original = i.games['MS-DOS', DOOM].number
        ultimate = i.games['MS-DOS', ULTIMATE].number
        self.assertNotEqual(original, i.games['Windows 9x', DOOM].number)

        def links(path):
            return {(owner, role, basis) for owner, asset, role, basis, _ in i.links
                    if asset == i.assets[path].number}

        self.assertEqual(links(self.cover), {(original, 'artwork', 'exogui_title'),
                                            (original, 'artwork', 'launchbox_title')})
        self.assertEqual(links(self.preview), {(ultimate, 'launcher_preview', 'launchbox_cache_guid')})
        self.assertIn((original, 'artwork', 'exogui_title_guid'),
                      links('Images/MS-DOS/Disc/DOOM.' + DOOM + '-01.png'))
        self.assertEqual(links(self.weird), {(original, 'artwork', 'launchbox_image_crc')})
        self.assertEqual(i.image_evidence[0][2:5], ('remote-scan.jpg', 745, 'Box - Back'))
        self.assertIn((original, 'extra', 'companion_pack_member'), links(self.extra))
        self.assertIn((original, 'manual', 'ManualPath'), links(self.manual))
        self.assertEqual(sum(no == i.assets[self.extra].number for no, _ in i.locations), 2)
        self.assertTrue(any(kind == 'different_copies' and ref == self.manual for kind, ref, *_ in i.issues))
        self.assertTrue(any(kind == 'invalid_archive_path' for kind, *_ in i.issues))
        self.assertEqual(i.counts()['game_package_links_by_list'], {'MS-DOS': 2, 'Windows 9x': 1})
        self.assertEqual(i.revision, scan(self.root).revision)
        self.file(self.weird, b'changed')
        self.assertNotEqual(i.revision, scan(self.root).revision)

    def test_reused_database_id_does_not_extend_the_frontends_artwork_bindings(self):
        path = self.root / 'xml/all/MS-DOS.xml'
        tree = parse(path)
        game = SubElement(tree.getroot(), 'Game')
        for key, value in {'Title': 'Another title', 'Platform': 'MS-DOS', 'DatabaseID': '745',
                           'ID': '33333333-3333-4333-a333-333333333333'}.items():
            SubElement(game, key).text = value
        tree.write(path)
        with closing(sqlite3.connect(self.root / 'Metadata/LaunchBox.Metadata.db')) as db, db:
            db.execute('INSERT INTO GameImages VALUES(?,?,?,?,?)',
                       ('cover-from-index.jpg', 745, 'Box - Front', 'World', crc32(b'cover')))
        i = scan(self.root)
        original = i.games['MS-DOS', DOOM].number
        self.assertEqual({owner for owner, num, *_ in i.links if num == i.assets[self.cover].number}, {original})
        self.assertTrue(any(kind == 'ambiguous_checksum_owner' and path == self.weird
                            for kind, path, *_ in i.issues))

    @unittest.skipUnless(os.getenv('GAMEDB_TEST_POSTGRES'), 'PostgreSQL integration')
    def test_atomic_idempotent_publication(self):
        i = scan(self.root)
        with create_database_engine().connect() as c, c.begin() as outer:
            class Savepoint:
                @contextmanager
                def begin(self):
                    with c.begin_nested():
                        yield c

            def interrupt(stage):
                if stage == 'Writing staging.exo_location':
                    raise RuntimeError('interrupted')

            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                publish(Savepoint(), self.root, i, interrupt)
            first = publish(Savepoint(), self.root, i)
            self.assertFalse(first['already_imported'])
            again = publish(Savepoint(), self.root, i)
            self.assertTrue(again['already_imported'])
            self.assertEqual(again['snapshot_id'], first['snapshot_id'])
            for table, count in [(schema.location, len(i.locations)), (schema.link, len(i.links)),
                                 (schema.image_evidence, len(i.image_evidence))]:
                self.assertEqual(c.execute(select(func.count()).select_from(table).where(
                    table.c.snapshot_id == first['snapshot_id'])).scalar_one(), count)
            outer.rollback()
