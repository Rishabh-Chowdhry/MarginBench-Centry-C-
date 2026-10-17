"""Baseline: the manuscript's Algorithm 1 (cost-stratified, confirmation-aware
margin estimation), made concrete so it can be run.

The manuscript leaves the "predefined confidence and multiplicity rule"
unspecified. Two concretisations are provided:

  "wilson-T"   : Wilson lower bound at level eps / T (Bonferroni over the T
                 candidates confirmed at one budget). Faithful to the text
                 ("Wilson ... as pre-registered"), but it never corrects for the
                 K budget levels it tests in sequence.
  "cp-KT"      : exact Clopper-Pearson lower bound at level eps / (K T).
                 A valid repair (union bound over all K*T confirmation tests).

Discovery seeds and confirmation seeds are disjoint fixed sets shared by all
candidates, as in the manuscript. Outcomes are deterministic per (candidate,
seed); the confirmation set is used only for confirmation, so selection does not
touch it (the Stage-2 CE5 failure needs reuse, which Algorithm 1 avoids).
"""

import math
from dataclasses import dataclass

import numpy as np

from fresco.certificates import binom_tail


def _norm_ppf(q):
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def wilson_lower(k, n, level):
    z = _norm_ppf(1 - level)
    p = k / n
    d = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d


def cp_lower(k, n, level):
    """Exact one-sided Clopper-Pearson lower bound: largest p with P(Bin(n,p) >= k) <= level."""
    if k == 0:
        return 0.0
    lo, hi = 0.0, k / n
    for _ in range(60):
        mid = (lo + hi) / 2
        if binom_tail(n, mid, k) <= level:
            lo = mid
        else:
            hi = mid
    return lo


@dataclass
class Alg1Config:
    alpha: float = 0.2
    eps: float = 0.05
    candidates_per_level: int = 40   # q
    discovery_reps: int = 5          # r_d
    top: int = 3                     # T candidates sent to confirmation
    holdout_reps: int = 30           # r_h
    rule: str = "wilson-T"           # or "cp-KT"


def run_alg1(reservoirs, cfg, rng):
    """reservoirs: list of K callables rng -> p (as in fresco.lexis). Returns dict
    with b_hat, slots used to reach it, and whether the witness is a true null."""
    K = len(reservoirs)
    level = cfg.eps / cfg.top if cfg.rule == "wilson-T" else cfg.eps / (K * cfg.top)
    lower = wilson_lower if cfg.rule == "wilson-T" else cp_lower
    slots = 0
    for k in range(K):
        ps = np.array([reservoirs[k](rng) for _ in range(cfg.candidates_per_level)])
        disc = (rng.random((len(ps), cfg.discovery_reps)) < ps[:, None]).sum(axis=1)
        slots += len(ps) * cfg.discovery_reps
        order = np.argsort(-disc, kind="stable")[: cfg.top]
        for idx in order:
            hits = int((rng.random(cfg.holdout_reps) < ps[idx]).sum())
            slots += cfg.holdout_reps
            if lower(hits, cfg.holdout_reps, level) >= cfg.alpha:
                return {"b_hat": k + 1, "slots": slots, "false": bool(ps[idx] <= cfg.alpha)}
    return {"b_hat": None, "slots": slots, "false": False}
