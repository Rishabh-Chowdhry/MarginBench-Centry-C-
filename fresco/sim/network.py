"""Unreliable network: delay, loss, duplication, reordering, partitions.

Reordering follows from independent per-message delays. Requests are retried by
the sender until answered (at-least-once), so loss turns into duplicates at the
receiver; the protocol must absorb both.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NetConfig:
    delay_mean: float = 0.05      # seconds, exponential
    drop: float = 0.0
    duplicate: float = 0.0
    partitions: tuple = ()        # ((t_start, t_end, frozenset(node names)), ...) cut from the ledger


@dataclass
class NetStats:
    sent: int = 0
    delivered: int = 0
    dropped: int = 0
    duplicated: int = 0
    partitioned: int = 0


class Network:
    def __init__(self, engine, cfg):
        self.engine = engine
        self.cfg = cfg
        self.rng = engine.rng("network")
        self.nodes = {}
        self.stats = NetStats()

    def attach(self, name, handler):
        self.nodes[name] = handler

    @staticmethod
    def base(name):
        return name.split(".", 1)[0]          # worker incarnations are "<name>.<n>"

    def _cut(self, a, b):
        a, b = self.base(a), self.base(b)
        t = self.engine.now
        for t0, t1, group in self.cfg.partitions:
            if t0 <= t < t1 and ((a in group) != (b in group)):
                return True
        return False

    def send(self, msg):
        self.stats.sent += 1
        if self._cut(msg.src, msg.dst):
            self.stats.partitioned += 1
            return
        if self.rng.random() < self.cfg.drop:
            self.stats.dropped += 1
            return
        copies = 2 if self.rng.random() < self.cfg.duplicate else 1
        self.stats.duplicated += copies - 1
        for _ in range(copies):
            self.engine.after(self.rng.exponential(self.cfg.delay_mean), self._deliver, msg)

    def _deliver(self, msg):
        handler = self.nodes.get(self.base(msg.dst))
        if handler is None or self._cut(msg.src, msg.dst):
            self.stats.partitioned += 1
            return
        self.stats.delivered += 1
        handler(msg)
