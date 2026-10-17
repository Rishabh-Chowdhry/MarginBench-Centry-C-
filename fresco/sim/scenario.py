"""Synthetic scenario: per-level reservoirs with known ground truth.

A candidate is an integer `content` at a cost level. Its violation probability
p(level, content) is a fixed hash-derived value, so ground truth (which
candidates are null, mu_k, k*) is known exactly. Slot outcome Y is a
deterministic function of (content, key): replaying a key reproduces Y (replay
mode). Latency and executor crashes depend on Y (outcome-correlated faults,
Stage 2 CE2) and on the attempt, so a re-run of the same key may succeed.
"""

import math
from dataclasses import dataclass, field

from fresco.sim.engine import hash01


@dataclass(frozen=True)
class Level:
    pi: float = 0.0          # fraction of contents that are true violators
    p_good: float = 0.6      # their violation probability (> alpha)
    p_null_max: float = 0.2  # null contents have p ~ U(0, p_null_max) (<= alpha)
    space: int = 10**6       # content space size (D_k is uniform over it)
    null_at_boundary: bool = False  # nulls have p = p_null_max exactly (least favourable)


@dataclass(frozen=True)
class FaultModel:
    t_benign: float = 20.0       # mean slot latency (s) when Y = 0
    t_violation: float = 30.0    # mean slot latency (s) when Y = 1
    sigma: float = 0.5           # lognormal shape
    crash_benign: float = 0.0    # executor crash prob per attempt when Y = 0
    crash_violation: float = 0.0  # ... when Y = 1


@dataclass(frozen=True)
class Scenario:
    levels: tuple = field(default_factory=lambda: (Level(), Level(), Level(pi=0.05), Level(pi=0.1)))
    alpha: float = 0.2
    seed: int = 1
    faults: FaultModel = field(default_factory=FaultModel)

    def p(self, level, content):
        lv = self.levels[level - 1]
        u = hash01(self.seed, "p", level, content)
        if u < lv.pi:
            return lv.p_good
        if lv.null_at_boundary:
            return lv.p_null_max
        return lv.p_null_max * hash01(self.seed, "pn", level, content)

    def outcome(self, level, content, key):
        return int(hash01(self.seed, "y", level, content, key) < self.p(level, content))

    def execution(self, level, content, key, attempt):
        """Returns (y, latency, crashed) for one executor attempt."""
        y = self.outcome(level, content, key)
        f = self.faults
        mean = f.t_violation if y else f.t_benign
        z = _std_normal(hash01(self.seed, "lat", key, attempt))
        latency = mean * math.exp(f.sigma * z - f.sigma ** 2 / 2)
        crashed = hash01(self.seed, "crash", key, attempt) < (f.crash_violation if y else f.crash_benign)
        return y, latency, crashed

    def audit_content(self, level, seed):
        return seed % self.levels[level - 1].space

    def is_null(self, level, content):
        return self.p(level, content) <= self.alpha

    def mu(self, level):
        lv = self.levels[level - 1]
        return lv.pi if lv.p_good >= self.alpha else 0.0

    def k_star(self):
        for i, lv in enumerate(self.levels, start=1):
            if lv.pi > 0 and lv.p_good > self.alpha:
                return i
        return None


def _std_normal(u):
    # probit by the Abramowitz-Stegun 26.2.23 rational approximation (|error| < 4.5e-4);
    # one uniform per draw keeps latency a deterministic function of (key, attempt)
    u = min(max(u, 1e-12), 1 - 1e-12)
    t = math.sqrt(-2 * math.log(min(u, 1 - u)))
    z = t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / (1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t ** 3)
    return z if u > 0.5 else -z
