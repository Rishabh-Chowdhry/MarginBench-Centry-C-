"""Statistical analysis helpers for Stage 4 (numpy only).

Time-to-target outcomes are administratively censored at a common horizon H,
so every comparison uses restricted means (RMST, mean of min(T, H)) and the
probability of reaching the target by H; rank tests treat censored values as
ties at H, which is valid for a common censoring time.
"""

import math

import numpy as np


def wilson(k, n, z=1.96):
    if n == 0:
        return (math.nan, 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def censor(values, horizon):
    """None (target not reached) -> horizon; returns array and event indicator."""
    v = np.array([horizon if x is None else min(float(x), horizon) for x in values])
    e = np.array([x is not None and float(x) <= horizon for x in values])
    return v, e


def bootstrap_ci(x, stat=np.mean, reps=4000, seed=0, alpha=0.05):
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    boots = np.array([stat(x[rng.integers(len(x), size=len(x))]) for _ in range(reps)])
    return float(stat(x)), float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))


def bootstrap_ratio_ci(x, y, stat=np.mean, reps=4000, seed=0, alpha=0.05):
    """CI for stat(x) / stat(y), independent resampling of the two groups."""
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x, float), np.asarray(y, float)
    r = []
    for _ in range(reps):
        sx = stat(x[rng.integers(len(x), size=len(x))])
        sy = stat(y[rng.integers(len(y), size=len(y))])
        r.append(sx / sy if sy > 0 else math.inf)
    return float(stat(x) / stat(y)), float(np.quantile(r, alpha / 2)), float(np.quantile(r, 1 - alpha / 2))


def mann_whitney(x, y):
    """Two-sided Mann-Whitney U with tie correction (normal approximation).
    Returns (U, p_value, rank_biserial) with rank_biserial = P(X<Y) - P(X>Y)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n1, n2 = len(x), len(y)
    allv = np.concatenate([x, y])
    order = np.argsort(allv, kind="mergesort")
    ranks = np.empty(len(allv))
    sv = allv[order]
    i = 0
    tie_term = 0.0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    r1 = ranks[:n1].sum()
    u1 = r1 - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    n = n1 + n2
    var = n1 * n2 / 12 * ((n + 1) - tie_term / (n * (n - 1)))
    if var <= 0:
        return u1, 1.0, 0.0
    z = (u1 - mu - 0.5 * np.sign(u1 - mu)) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    rbc = 1 - 2 * u1 / (n1 * n2)          # >0 means x tends to be smaller than y
    return float(u1), float(p), float(rbc)


def holm(pvals):
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * p[idx])
        adj[idx] = min(1.0, running)
    return adj


def kaplan_meier(times, events):
    """Product-limit survival curve S(t) for time-to-target (event = reached)."""
    t = np.asarray(times, float)
    e = np.asarray(events, bool)
    uniq = np.unique(t[e])
    s, out_t, out_s = 1.0, [0.0], [1.0]
    for u in uniq:
        at_risk = np.sum(t >= u)
        d = np.sum((t == u) & e)
        s *= 1 - d / at_risk
        out_t.append(float(u))
        out_s.append(s)
    return np.array(out_t), np.array(out_s)
