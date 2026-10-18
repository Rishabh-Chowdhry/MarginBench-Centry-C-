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


def run_alg1_multipass(reservoirs, cfg, rng, budget, stop_at_level=0):
    """Repaired Algorithm 1 repeated in passes until the oracle budget is spent.
    Pass n tests each of its K*T confirmations with an exact Clopper-Pearson bound
    at level eps / (n (n + 1) K T), so the total error over all passes is <= eps.
    Later passes only revisit levels below the current b_hat."""
    K = len(reservoirs)
    b_hat, slots, false, n = math.inf, 0, False, 0
    while True:
        n += 1
        level = cfg.eps / (n * (n + 1) * K * cfg.top)
        progressed = False
        for k in range(K):
            if k + 1 >= b_hat:
                break
            if slots + cfg.candidates_per_level * cfg.discovery_reps > budget:
                return {"b_hat": None if b_hat == math.inf else b_hat, "slots": slots, "false": false}
            ps = np.array([reservoirs[k](rng) for _ in range(cfg.candidates_per_level)])
            disc = (rng.random((len(ps), cfg.discovery_reps)) < ps[:, None]).sum(axis=1)
            slots += len(ps) * cfg.discovery_reps
            progressed = True
            for idx in np.argsort(-disc, kind="stable")[: cfg.top]:
                if slots + cfg.holdout_reps > budget:
                    return {"b_hat": None if b_hat == math.inf else b_hat, "slots": slots, "false": false}
                hits = int((rng.random(cfg.holdout_reps) < ps[idx]).sum())
                slots += cfg.holdout_reps
                if cp_lower(hits, cfg.holdout_reps, level) >= cfg.alpha:
                    b_hat = k + 1
                    false = false or bool(ps[idx] <= cfg.alpha)
                    break
            if b_hat <= k + 1:
                break
        if not progressed or b_hat <= max(stop_at_level, 1):
            return {"b_hat": None if b_hat == math.inf else b_hat, "slots": slots, "false": false}
