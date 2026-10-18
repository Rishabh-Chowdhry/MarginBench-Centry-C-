"""E9 (added during the execution-rules reframing; not preregistered):
do the executor defaults also break *fixed-n* confirmation (the exact
Clopper-Pearson test of repaired Algorithm 1), and do the rules restore it?

A run is one confirmation family of K*T = 12 boundary-null candidates (p = alpha
= 0.2), each tested once with n = 30 slots at level eps/12 (the repaired
Algorithm 1 worst case). Family-wise false confirmation is reported.

Defaults modelled (each alone):
  duplicates   : each result delivered twice w.p. 0.3; a naive collector stops at
                 n received results (duplicates take the place of fresh slots)
  fresh retry  : benign episodes crash w.p. 0.3, violating w.p. 0.1; crashed
                 slots silently re-run with a fresh key
  first-n      : 60 slots launched, the first 30 to *arrive* are used; violating
                 episodes return faster (evidence chosen by arrival, not index)
  local budget : W = 8 workers each spend the full eps on their own family

Rules applied: index-determined slot set, exactly-once, crash -> Y = 0 without
fresh retry, one global budget.

Run: python3 -I experiments/e9_fixed_n_rules.py [runs]   (default 50000)
"""

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from analysis.stats import wilson  # noqa: E402
from fresco.certificates import binom_tail  # noqa: E402

ALPHA, EPS, N, FAMILY, SEED = 0.2, 0.05, 30, 12, 20261018


def critical_count(level):
    """Smallest s with P(Bin(N, alpha) >= s) <= level: confirm iff successes >= s.
    Equivalent to the exact Clopper-Pearson lower bound being >= alpha."""
    for s in range(N + 1):
        if binom_tail(N, ALPHA, s) <= level:
            return s
    return N + 1


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    rng = np.random.default_rng(SEED)
    s_star = critical_count(EPS / FAMILY)
    rows = {}

    def fam(successes):            # successes: (runs, FAMILY) -> family-wise false confirmation
        return (successes >= s_star).any(axis=1)

    shape = (runs, FAMILY)
    # rules applied, no faults
    rows["rules applied, no faults"] = fam(rng.binomial(N, ALPHA, shape))
    # rules applied under crashes 0.3 / 0.1: crash -> 0, no retry
    y = rng.random(shape + (N,)) < ALPHA
    crash = np.where(y, rng.random(y.shape) < 0.1, rng.random(y.shape) < 0.3)
    rows["rules applied, crashes 0.3/0.1 imputed as 0"] = fam((y & ~crash).sum(axis=2))
    # duplicates: collector takes the first N received; each slot result arrives once or twice
    y = rng.random(shape + (N,)) < ALPHA
    dup = rng.random(shape + (N,)) < 0.3
    stream = np.concatenate([y, np.where(dup, y, -1)], axis=2)        # -1 = no duplicate
    order = np.argsort(rng.random(stream.shape), axis=2)               # random arrival order
    stream = np.take_along_axis(stream, order, axis=2)
    valid = stream >= 0
    csum = np.cumsum(valid, axis=2)
    take = valid & (csum <= N)
    succ = (np.where(take, stream, 0)).sum(axis=2)
    rows["default: duplicates counted (dup 0.3)"] = fam(succ)
    # fresh retry with outcome-correlated crashes
    p_eff = ALPHA * 0.9 / (ALPHA * 0.9 + (1 - ALPHA) * 0.7)
    rows[f"default: crash -> fresh-key retry (effective p = {p_eff:.3f})"] = fam(rng.binomial(N, p_eff, shape))
    # first N arrivals out of 2N launched, violations faster (latency 5 s vs 30 s, lognormal)
    y = rng.random(shape + (2 * N,)) < ALPHA
    lat = np.where(y, 5.0, 30.0) * np.exp(0.5 * rng.standard_normal(y.shape))
    first = np.argsort(lat, axis=2)[:, :, :N]
    rows["default: first n of 2n arrivals used (violations faster)"] = fam(np.take_along_axis(y, first, axis=2).sum(axis=2))
    # local budget: 8 workers each spend eps on their own 12-test family
    w8 = (rng.binomial(N, ALPHA, (runs // 8, 8, FAMILY)) >= s_star).any(axis=(1, 2))
    rows["default: worker-local budget, W = 8"] = w8
    s_global = critical_count(EPS / (8 * FAMILY))
    g8 = (rng.binomial(N, ALPHA, (runs // 8, 8, FAMILY)) >= s_global).any(axis=(1, 2))
    rows["rules applied: one global budget, W = 8"] = g8

    out = {"alpha": ALPHA, "eps": EPS, "n": N, "family": FAMILY, "critical_count": s_star, "runs": runs,
           "results": {}}
    print(f"fixed-n CP confirmation: n={N}, family={FAMILY}, level eps/12 -> confirm iff >= {s_star} successes")
    print(f"{'configuration':60s} P(false confirmation)  [95% Wilson]")
    for name, v in rows.items():
        k, n = int(v.sum()), len(v)
        p, lo, hi = wilson(k, n)
        out["results"][name] = {"false": k, "runs": n, "p": p, "lo": lo, "hi": hi}
        print(f"{name:60s} {p:.4f}  [{lo:.4f}, {hi:.4f}]")
    path = pathlib.Path(__file__).resolve().parents[1] / "results" / "raw" / "e9_fixed_n_rules.json"
    path.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
