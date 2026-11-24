"""Bounded process-local JSON responses with shared concurrent loads."""

from collections import OrderedDict
from concurrent.futures import Future
import json
import threading
import time


class JsonResponseCache:
    def __init__(self, max_entries=256, max_bytes=8 * 1024 * 1024,
                 ttl=300, clock=time.monotonic):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.ttl = ttl
        self.clock = clock
        self._entries = OrderedDict()
        self._bytes = 0
        self._inflight = {}
        self._generation = 0
        self._lock = threading.Lock()

    def get_or_load(self, key, loader):
        return json.loads(self.get_bytes(key, loader))

    def get_bytes(self, key, loader):
        return self.get_encoded(key, lambda: json.dumps(
            loader(), ensure_ascii=False, separators=(',', ':')
        ).encode('utf-8'))

    def get_encoded(self, key, loader):
        """Cache an already encoded JSON response, including compressed variants."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                expires, body, size = entry
                if expires is None or self.clock() < expires:
                    self._entries.move_to_end(key)
                    return body
                del self._entries[key]
                self._bytes -= size
            pending = self._inflight.get(key)
            owner = pending is None
            if owner:
                pending = Future()
                self._inflight[key] = pending
            generation = self._generation

        if not owner:
            return pending.result()
        try:
            body = loader()
            size = len(body) + len(key.encode('utf-8'))
            with self._lock:
                if generation == self._generation and size <= self.max_bytes:
                    expires = None if self.ttl is None else self.clock() + self.ttl
                    self._entries[key] = (expires, body, size)
                    self._bytes += size
                    while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                        _, (_, _, evicted_size) = self._entries.popitem(last=False)
                        self._bytes -= evicted_size
                if self._inflight.get(key) is pending:
                    del self._inflight[key]
            pending.set_result(body)
            return body
        except BaseException as error:
            with self._lock:
                if self._inflight.get(key) is pending:
                    del self._inflight[key]
            pending.set_exception(error)
            raise

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._generation += 1
            # Existing callers still receive their in-flight answer, but it
            # cannot repopulate the cleared cache or block a fresh request.
            self._inflight.clear()
