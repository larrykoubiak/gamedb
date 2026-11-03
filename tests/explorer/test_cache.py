import subprocess
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gamedb.explorer.cache import JsonResponseCache
from gamedb.explorer.repository import CatalogRepository
from gamedb.explorer.server import ExplorerServer


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


class MetadataOptionsCacheTests(unittest.TestCase):
    def test_equivalent_filter_order_and_own_field_selection_share_an_entry(self):
        client = Mock()
        client.query.return_value = {'total': 1, 'items': [{'value': 'Action', 'count': 2}]}
        repository = CatalogRepository('default', client)
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
                server = SimpleNamespace(repository=SimpleNamespace(metadata_options_cache=cache))

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
