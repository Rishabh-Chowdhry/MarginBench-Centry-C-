"""Deterministic discrete-event engine.

Virtual time only; ties are broken by insertion sequence; every random stream is
derived from (master seed, stable name) with SHA-256, never from Python's hash()
or the wall clock. Same config + seed => identical event trace.
"""

import hashlib
import heapq

import numpy as np


def stable_int(*parts):
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big")


def hash01(*parts):
    return stable_int(*parts) / 2**64


class Engine:
    def __init__(self, seed):
        self.seed = seed
        self.now = 0.0
        self._q = []
        self._seq = 0
        self.stopped = False
        self.events_run = 0
        self._trace = hashlib.sha256()

    def at(self, t, fn, *args):
        heapq.heappush(self._q, (t, self._seq, fn, args))
        self._seq += 1

    def after(self, dt, fn, *args):
        self.at(self.now + dt, fn, *args)

    def rng(self, *name):
        return np.random.default_rng(stable_int(self.seed, *name))

    def trace(self, *record):
        self._trace.update(repr(record).encode())

    def trace_digest(self):
        return self._trace.hexdigest()

    def run(self, until):
        while self._q and not self.stopped:
            t, _, fn, args = heapq.heappop(self._q)
            if t > until:
                break
            self.now = t
            self.events_run += 1
            fn(*args)
        return self.now
