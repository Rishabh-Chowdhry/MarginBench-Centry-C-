"""LEXIS-S: screening + e-process confirmation (Stage 6 doc, section 1).

Levels are processed in ascending cost. In pass n (error budget eps/(n(n+1)),
split evenly over the K levels) each level screens q candidates with r_d
scouting trials on keys independent of confirmation keys, promotes the top T,
and confirms each promoted candidate with a betting e-process on fresh trials.
Weight and bet prior are fixed at promotion from scouting data only, so they
are registration information and Theorem 1 applies unchanged.

Slot-level single-process specification over synthetic reservoirs (as
fresco.lexis); reservoirs are callables rng -> p.
"""

import math
from dataclasses import dataclass

import numpy as np

from fresco.eprocess import EProcess, PlugInKelly, PriorKelly


@dataclass
class HybridConfig:
    alpha: float = 0.2
    eps: float = 0.05
    q: int = 40                 # candidates screened per level and pass
    r_d: int = 5                # scouting trials per candidate (never evidence)
    T: int = 3                  # candidates promoted per level and pass
    cap: int = 30               # max confirmation trials per promoted candidate
    budget: int = 0             # 0 = single pass; > 0 = multi-pass until budget
    weighting: str = "scout"    # "scout" (w = hits + 1, prior from scouting) or "uniform"
    shrink: float = 0.5         # pseudo-count shrinkage of the scouting prior
    bet_cap: float = 0.5
    stop_at_level: int = 0      # stop once b_hat <= this level


def run_hybrid(reservoirs, cfg, rng):
    """Returns dict(b_hat, slots, false, registrations, passes)."""
    K = len(reservoirs)
    b_hat = math.inf
    slots = 0
    false = False
    registrations = 0
    n = 0
    while True:
        n += 1
        a_level = cfg.eps / (n * (n + 1)) / K
        progressed = False
        for k in range(K):
            if k + 1 >= b_hat:
                break
            if cfg.budget and slots + cfg.q * cfg.r_d > cfg.budget:
                return _out(b_hat, slots, false, registrations, n)
            ps = np.array([reservoirs[k](rng) for _ in range(cfg.q)])
            hits = (rng.random((cfg.q, cfg.r_d)) < ps[:, None]).sum(axis=1)
            slots += cfg.q * cfg.r_d
            progressed = True
            top = np.argsort(-hits, kind="stable")[: cfg.T]
            w = (hits[top] + 1.0) if cfg.weighting == "scout" else np.ones(len(top))
            for idx, wi in zip(top, w):
                a = a_level * wi / w.sum()
                registrations += 1
                if cfg.weighting == "scout":
                    h = float(hits[idx])
                    strategy = PriorKelly(cfg.shrink * h, cfg.shrink * (cfg.r_d - h), cap=cfg.bet_cap)
                else:
                    strategy = PlugInKelly(cap=cfg.bet_cap)
                ep = EProcess(cfg.alpha, strategy)
                for _ in range(cfg.cap):
                    if cfg.budget and slots >= cfg.budget:
                        return _out(b_hat, slots, false, registrations, n)
                    ep.update(int(rng.random() < ps[idx]))
                    slots += 1
                    if ep.crossed(a):
                        break
                if ep.crossed(a):
                    b_hat = k + 1
                    false = false or bool(ps[idx] <= cfg.alpha)
                    break
            if b_hat <= k + 1:
                break                            # levels >= b_hat are no longer useful
        if not cfg.budget or not progressed or b_hat <= max(cfg.stop_at_level, 1):
            return _out(b_hat, slots, false, registrations, n)


def _out(b_hat, slots, false, registrations, passes):
    return {"b_hat": None if b_hat == math.inf else b_hat, "slots": slots, "false": false,
            "registrations": registrations, "passes": passes}
