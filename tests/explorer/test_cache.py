import subprocess
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gamedb.explorer.cache import JsonResponseCache
from gamedb.explorer.repository import CatalogChanged, CatalogRepository
from gamedb.explorer.server import ExplorerHandler, ExplorerServer


class JsonResponseCacheTests(unittest.TestCase):
    def test_expiry_is_from_load_and_cached_responses_cannot_be_mutated(self):
        now = [0]
        cache = JsonResponseCache(ttl=10, clock=lambda: now[0])
        load = Mock(return_value={'items': ['first']})
        cache.get_or_load('key', load)['items'].append('changed')
        now[0] = 9
        self.assertEqual(cache.get_or_load('key', load), {'items': ['first']})
        self.assertEqual(load.call_count, 1)
        now[0] = 10
        cache.get_or_load('key', load)
        self.assertEqual(load.call_count, 2)

    def test_entry_and_byte_limits_evict_least_recently_used(self):
        cache = JsonResponseCache(max_entries=2)
        load = Mock(return_value={})
        for key in ('a', 'b', 'a', 'c', 'a'):
            cache.get_or_load(key, load)
        self.assertEqual(load.call_count, 3)
        cache.get_or_load('b', load)
        self.assertEqual(load.call_count, 4)
        # Each entry occupies three serialized bytes: a one-byte key and {}.
        cache = JsonResponseCache(max_bytes=5)
        load.reset_mock()
        for key in ('a', 'b', 'b', 'a'):
            cache.get_or_load(key, load)
        self.assertEqual(load.call_count, 3)
        oversized = Mock(return_value={'large': 'x' * 100})
        for _ in range(2):
            cache.get_or_load('oversized', oversized)
        self.assertEqual(oversized.call_count, 2)
        self.assertEqual(cache.get_or_load('a', load), {})
        self.assertEqual(load.call_count, 3)

    def test_concurrent_identical_queries_share_success_or_failure_and_failures_retry(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                cache = JsonResponseCache()
                started, waiting, release = threading.Event(), threading.Event(), threading.Event()

                class ObservedFuture(Future):
                    def result(self, timeout=None):
                        waiting.set()
                        return super().result(timeout)

                def load():
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError('test did not release loader')
                    if fail:
                        raise ValueError('database unavailable')
                    return {'items': ['value']}

                loader = Mock(side_effect=load)
                with patch('gamedb.explorer.cache.Future', ObservedFuture), ThreadPoolExecutor(2) as pool:
                    first = pool.submit(cache.get_or_load, 'same', loader)
                    self.assertTrue(started.wait(2))
                    second = pool.submit(cache.get_or_load, 'same', loader)
                    try:
                        self.assertTrue(waiting.wait(2))
                    finally:
                        release.set()
                    for result in (first, second):
                        if fail:
                            with self.assertRaisesRegex(ValueError, 'database unavailable'):
                                result.result(2)
                        else:
                            self.assertEqual(result.result(2), {'items': ['value']})
                self.assertEqual(loader.call_count, 1)
                if fail:
                    self.assertEqual(cache.get_or_load('same', lambda: {}), {})

    def test_clear_during_load_does_not_restore_stale_data_or_block_other_keys(self):
        cache = JsonResponseCache()
        started, release = threading.Event(), threading.Event()

        def old_load():
            started.set()
            if not release.wait(5):
                raise TimeoutError('test did not release loader')
            return {'generation': 'old'}

        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(cache.get_or_load, 'key', old_load)
            self.assertTrue(started.wait(2))
            try:
                other = pool.submit(cache.get_or_load, 'other', lambda: {})
                self.assertEqual(other.result(2), {})
                cache.clear()
                fresh = pool.submit(cache.get_or_load, 'key', lambda: {'generation': 'new'})
                self.assertEqual(fresh.result(2), {'generation': 'new'})
            finally:
                release.set()
            self.assertEqual(first.result(2), {'generation': 'old'})
        self.assertEqual(cache.get_or_load('key', lambda: self.fail('cache missed')),
                         {'generation': 'new'})


class ListingCacheTests(unittest.TestCase):
    def test_pages_are_scoped_to_the_query_and_published_revision(self):
        client = Mock()
        client.query.return_value = {'items': ['original']}
        repository = CatalogRepository('default', client)
        repository._published_revision = Mock(return_value='first')
        filters = {'genre': ['RPG', 'Action'], 'developer': ['Nintendo']}
        repository.titles(259, 100, 0, 'Wonder', filters)['items'].clear()
        reordered = {'developer': ['Nintendo'], 'genre': ['Action', 'RPG', 'RPG']}
        self.assertEqual(repository.titles(259, 100, 0, 'Wonder', reordered)['items'], ['original'])
        self.assertEqual(client.query.call_count, 1)
        for args in [(260, 100, 0, 'Wonder', filters), (259, 50, 0, 'Wonder', filters),
                     (259, 100, 100, 'Wonder', filters), (259, 100, 0, 'Mario', filters),
                     (259, 100, 0, 'Wonder', {}), (None, 100, 0, 'Wonder', filters)]:
            repository.titles(*args)
        self.assertEqual(client.query.call_count, 7)
        repository._published_revision.return_value = 'second'
        client.query.return_value = {'items': ['new preferred release']}
        self.assertEqual(repository.titles(259, 100, 0, 'Wonder', filters)['items'], ['new preferred release'])
        self.assertEqual(client.query.call_count, 8)

    def test_refresh_during_a_load_discards_the_response(self):
        client = Mock()
        client.query.side_effect = [['old'], ['new']]
        repository = CatalogRepository('default', client)
        repository._published_revision = Mock(side_effect=['one', 'two', 'two', 'two', 'two'])
        with self.assertRaises(CatalogChanged):
            repository.systems()
        self.assertEqual(repository.systems(), ['new'])
        self.assertEqual(repository.systems(), ['new'])
        self.assertEqual(client.query.call_count, 2)

    def test_equivalent_filter_order_and_own_field_selection_share_an_entry(self):
        client = Mock()
        client.query.return_value = {'total': 1, 'items': [{'value': 'Action', 'count': 2}]}
        repository = CatalogRepository('default', client)
        repository._published_revision = Mock(return_value='first')
        first = repository.metadata_options('genre', 1, 'Mario', {
            'genre': ['Action'], 'developer': ['Nintendo', 'Nintendo'],
            'publisher': ['B', 'A'],
        })
        second = repository.metadata_options('genre', 1, 'Mario', {
            'publisher': ['A', 'B'], 'genre': ['Adventure'], 'developer': ['Nintendo'],
        })
        self.assertEqual(first, second)
        self.assertEqual(client.query.call_count, 1)
        for kwargs in ({'key': 'developer'}, {'system_id': 2}, {'system_id': None},
                       {'title_filter': 'Zelda'}, {'search': 'Action'},
                       {'metadata_filters': {'developer': ['Sega']}}):
            args = dict(key='genre', system_id=1, title_filter='Mario', metadata_filters={
                'developer': ['Nintendo'], 'publisher': ['A', 'B']})
            args.update(kwargs)
            repository.metadata_options(**args)
        self.assertEqual(client.query.call_count, 7)
        repository.username = 'another-user'
        repository.metadata_options('genre', 1, 'Mario', {
            'developer': ['Nintendo'], 'publisher': ['A', 'B']})
        self.assertEqual(client.query.call_count, 8)

    def test_correction_rebuild_clears_cache_before_and_after_even_on_failure(self):
        for failure in (None, subprocess.CalledProcessError(1, ['rebuild'])):
            with self.subTest(failure=failure):
                cache = Mock()
                server = SimpleNamespace(repository=SimpleNamespace(listing_cache=cache))

                def rebuild(*args, **kwargs):
                    self.assertEqual(cache.clear.call_count, 1)
                    if failure:
                        raise failure

                with patch('gamedb.explorer.server.subprocess.run', side_effect=rebuild):
                    if failure:
                        with self.assertRaises(subprocess.CalledProcessError):
                            ExplorerServer.rebuild_software(server)
                    else:
                        ExplorerServer.rebuild_software(server)
                self.assertEqual(cache.clear.call_count, 2)


class LauncherSnapshotCacheTests(unittest.TestCase):
    def test_conditional_requests_eviction_and_refresh_during_assembly(self):
        class QuietHandler(ExplorerHandler):
            def log_message(self, *args):
                pass

        key = 'a' * 32
        path = f'/api/v1/systems/{key}/software'
        repository = CatalogRepository('default')
        repository._published_revision = Mock(return_value='initial')
        repository.systems = Mock(return_value=[{'key': key}])

        def build(system_key, revision, hide_rom_hacks=False):
            if revision == 'changing':
                repository._published_revision.return_value = 'published'
            return {'catalogRevision': revision, 'items': [] if hide_rom_hacks else [system_key]}

        repository.system_software = Mock(side_effect=build)
        with ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler) as server:
            server.repository = repository
            server.api_key = 'test-key'
            server.catalog_cache = JsonResponseCache(ttl=None)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()

            def get(url=path, etag=None, authorized=True):
                headers = {'Authorization': 'Bearer test-key'} if authorized else {}
                if etag:
                    headers['If-None-Match'] = etag
                connection = HTTPConnection(*server.server_address)
                try:
                    connection.request('GET', url, headers=headers)
                    response = connection.getresponse()
                    return response.status, response.getheader('ETag'), response.read()
                finally:
                    connection.close()

            try:
                status, etag, body = get()
                self.assertEqual((status, json.loads(body)['catalogRevision']), (200, 'initial'))
                self.assertEqual(get(), (status, etag, body))
                server.catalog_cache.clear()
                self.assertEqual(get(etag=etag), (304, etag, b''))
                self.assertEqual(get(etag=etag, authorized=False)[0], 401)
                repository.system_software.assert_called_once()
                repository.systems.return_value = []
                self.assertEqual(get(etag=etag)[0], 404)
                repository.systems.return_value = [{'key': key}]
                repository._published_revision.return_value = 'changing'
                status, new_etag, body = get(etag=etag)
                self.assertEqual((status, json.loads(body)['catalogRevision']), (200, 'published'))
                self.assertNotEqual(new_etag, etag)
                self.assertEqual(get(etag=new_etag), (304, new_etag, b''))
                self.assertEqual(repository.system_software.call_count, 3)
                filtered = path + '?hide_rom_hacks=1'
                status, filtered_etag, body = get(filtered, etag=new_etag)
                self.assertEqual((status, json.loads(body)['items']), (200, []))
                self.assertNotEqual(filtered_etag, new_etag)
                self.assertEqual(get(filtered, etag=filtered_etag), (304, filtered_etag, b''))
                self.assertEqual(get(path, etag=filtered_etag)[0], 200)
                self.assertEqual(get(path + '?hide_rom_hacks=invalid')[0], 400)
            finally:
                server.shutdown()
                thread.join()
