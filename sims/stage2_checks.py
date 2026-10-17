"""Stage-2 numerical checks of the propositions and counterexamples in
docs/stage2_framework_and_algorithm.md.

Synthetic Bernoulli oracles only. These checks test the mathematics (an
implementation that disagreed with a proven bound would expose a bug in the
proof or the code); they are not evidence about LLM agents.

Run:  python3 -I sims/stage2_checks.py            (about 1-3 minutes)
"""

import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.certificates import BernoulliUpperCS, zero_failure_upper  # noqa: E402
from fresco.eprocess import (EProcess, FixedBet, PlugInKelly, kl_bernoulli,  # noqa: E402
                             log_growth, wald_expected_stopping_bound)
from fresco.lexis import LexisConfig, run_lexis  # noqa: E402
from fresco.spending import polynomial_weight  # noqa: E402

SEED = 20261018
ALPHA = 0.2
EPS = 0.05


def ci(p, n):
    return 1.96 * math.sqrt(max(p * (1 - p), 1e-12) / n)


def report(name, value, n, bound, relation="<="):
    half = ci(value, n)
    if relation == "<=":
        ok = value - half <= bound
    else:
        ok = value + half >= bound
    print(f"  {name:58s} {value:8.4f} ±{half:.4f}  (claim {relation} {bound:.4f})  {'PASS' if ok else 'FAIL'}")
    return ok


def vec_crossing_fixed(y, lam, log_thr, weights=None):
    f = np.log1p(lam * (y - ALPHA))
    if weights is not None:
        f = f * weights
    return (np.cumsum(f, axis=1).max(axis=1) >= log_thr)


def vec_crossing_plugin(y, log_thr, cap=0.5, prior=0.5):
    n = np.arange(y.shape[1])
    s_prev = np.concatenate([np.zeros((y.shape[0], 1)), np.cumsum(y, axis=1)[:, :-1]], axis=1)
    p_hat = (s_prev + prior) / (n + 2 * prior)
    lam = np.clip((p_hat - ALPHA) / (ALPHA * (1 - ALPHA)), 0, cap / ALPHA)
    return np.cumsum(np.log1p(lam * (y - ALPHA)), axis=1).max(axis=1) >= log_thr


def check_validity(rng):
    print("[P1] Validity of LEXIS under adaptive generation, allocation and stopping")
    ok = True
    reps = 600
    # (a) every reservoir is at the least favourable null boundary p = alpha
    res_null = [lambda r: ALPHA] * 3
    cfg = LexisConfig(alpha=ALPHA, eps=EPS, budget=3000, cap=80)
    fc = np.mean([len(run_lexis(res_null, cfg, rng).confirmations) > 0 for _ in range(reps)])
    ok &= report("all-null reservoirs: P(any false confirmation)", fc, reps, EPS)

    # (b) mixed reservoirs: nulls uniform on [0, alpha], rare true violators at level 2-3
    def lvl(pi, p_good):
        return lambda r: p_good if r.random() < pi else r.uniform(0, ALPHA)
    res_mix = [lvl(0.0, 0.0), lvl(0.03, 0.5), lvl(0.10, 0.6)]
    false = 0
    for _ in range(reps):
        rep = run_lexis(res_mix, cfg, rng)
        false += any(p <= ALPHA for _, p, _ in rep.confirmations)
    ok &= report("mixed reservoirs: P(any confirmed candidate has p <= alpha)", false / reps, reps, EPS)

    # (c) adversarial continuation: keep a candidate only while its log-wealth is
    # within 1 nat of its running maximum, otherwise register a new one
    # (data-dependent stopping; budget spread over many candidates).
    reps_c = 1500
    hits = 0
    for _ in range(reps_c):
        j, slots, ep, a, crossed = 0, 0, None, None, False
        while slots < 1500 and not crossed:
            if ep is None or ep.log_e < ep.max_log_e - 1.0:
                j += 1
                ep, a = EProcess(ALPHA, PlugInKelly()), polynomial_weight(j, EPS)
            ep.update(int(rng.random() < ALPHA))
            slots += 1
            crossed = ep.crossed(a)
        hits += crossed
    ok &= report("adversarial continuation, p = alpha for all candidates", hits / reps_c, reps_c, EPS)
    return ok


def check_wald(rng):
    print("[P4] Wald bound on expected confirmation time (fixed Kelly bet)")
    ok = True
    for p1, p in ((0.4, 0.4), (0.4, 0.6), (0.6, 0.6)):
        bet = FixedBet.kelly(ALPHA, p1)
        a = EPS / 2
        bound = wald_expected_stopping_bound(a, bet.lam, ALPHA, p)
        reps, n = 20000, int(bound * 6) + 50
        y = (rng.random((reps, n)) < p).astype(float)
        logw = np.cumsum(np.log1p(bet.lam * (y - ALPHA)), axis=1)
        hit = logw >= math.log(1 / a)
        tau = np.where(hit.any(axis=1), hit.argmax(axis=1) + 1, n)
        emp = float(tau.mean())
        lower = math.log(1 / (2.4 * a)) / kl_bernoulli(p, ALPHA)
        good = lower * 0.9 <= emp <= bound * 1.02
        ok &= good
        print(f"  p1={p1} p={p}: E[tau] emp {emp:7.2f}; lower (Kaufmann-type) {lower:6.2f}; "
              f"Wald upper {bound:6.2f}  {'PASS' if good else 'FAIL'}")
    return ok


def check_counterexamples(rng):
    print("[P5] Necessity counterexamples (each rule removed)")
    log_thr = math.log(1 / EPS)
    reps, n = 20000, 600
    y = (rng.random((reps, n)) < ALPHA).astype(float)
    base = vec_crossing_fixed(y, 1.0, log_thr).mean()
    report("baseline (all rules kept), fixed bet", base, reps, EPS)

    # CE1: every result applied twice -> E_n^2; theory: error ~ O(sqrt(eps))
    dup = vec_crossing_fixed(y, 1.0, log_thr, np.full_like(y, 2.0)).mean()
    report("CE1 every result duplicated: exceeds eps", dup, reps, EPS, ">=")
    print(f"      (theory: crossing E^2 >= 1/eps  <=> E >= eps^-1/2, so error <= sqrt(eps) = {math.sqrt(EPS):.3f})")

    # CE2: outcome-correlated crash + fresh retry, consistent (plug-in) bet.
    c0, c1 = 0.3, 0.1
    p_eff = ALPHA * (1 - c1) / (ALPHA * (1 - c1) + (1 - ALPHA) * (1 - c0))
    print(f"      CE2 applied success prob p_eff = {p_eff:.3f} > alpha; KL = {kl_bernoulli(p_eff, ALPHA):.4f}")
    prev = 0.0
    for cap in (100, 1000, 4000):
        r = 4000
        yy = (rng.random((r, cap)) < p_eff).astype(float)
        e = vec_crossing_plugin(yy, log_thr).mean()
        report(f"CE2 crash->fresh retry, plug-in bet, slot cap {cap}", e, r, EPS, ">=")
        prev = e
    print(f"      (theory: a consistent test rejects p_eff > alpha a.s., so error -> 1 as cap -> inf; at cap 4000: {prev:.3f})")

    # CE3: parallel launch of m slots, processed in arrival order where violating
    # trajectories return first; plug-in bet.
    for m in (1, 8, 64):
        r = 4000
        yy = (rng.random((r, 640)) < ALPHA).astype(float)
        yy = -np.sort(-yy.reshape(r, 640 // m, m), axis=2).reshape(r, 640)
        e = vec_crossing_plugin(yy, log_thr).mean()
        report(f"CE3 arrival order, {m:2d} slots in flight", e, r, EPS, "<=" if m == 1 else ">=")

    # CE5: shared seed set + adaptive selection (deterministic seeded oracle).
    # 200 null candidates are scored on the same 20 fixed seeds; the best one is
    # then "confirmed" by re-evaluating on those same seeds.
    r = 4000
    hits = 0
    n_seeds, n_cand = 20, 200
    for _ in range(r):
        outcomes = (rng.random((n_cand, n_seeds)) < ALPHA).astype(float)  # Y(delta, sigma) fixed
        best = outcomes[outcomes.sum(axis=1).argmax()]
        ep = EProcess(ALPHA, FixedBet(1.0))
        for v in best:
            ep.update(int(v))
        hits += ep.crossed(EPS)
    report("CE5 shared fixed seeds reused for selection and confirmation", hits / r, r, EPS, ">=")


def check_certificates(rng):
    print("[P2/P3] Anytime-valid non-discovery certificates under adversarial stopping")
    ok = True
    beta = 0.05
    for q in (0.002, 0.01, 0.05):
        n0 = math.ceil(math.log(beta) / math.log(1 - q))
        exact = (1 - q) ** n0
        r = 200000
        first = rng.geometric(q, size=r)          # index of first success
        # adversary reports at time first-1 (last all-zero time), the most optimistic
        n_rep = first - 1
        wrong = np.mean([(n > 0) and (q > zero_failure_upper(n, beta)) for n in n_rep[:20000]])
        ok &= report(f"zero-failure bound, q={q}: P(q > U at optimistic stop)", wrong, 20000, beta)
        print(f"      exact worst case (1-q)^n0 = {exact:.4f}")
    r = 600
    for q in (0.05, 0.3):
        miss = 0
        for _ in range(r):
            cs = BernoulliUpperCS(beta, grid_size=200)
            for z in (rng.random(150) < q):
                cs.update(int(z))
                if q > cs.upper():
                    miss += 1
                    break
        ok &= report(f"betting upper CS, q={q}: P(exists n<=150: q > U_n)", miss / r, r, beta)
    return ok


def check_minimax(rng):
    print("[P6] Fixed-weight level scheduling: uniform weights are minimax")
    K, pi, p_good = 4, 0.05, 0.7
    out = {}
    for name, w in (("uniform", (1, 1, 1, 1)), ("cheap-first", (0.55, 0.25, 0.12, 0.08))):
        worst = 0
        for k_star in range(K):
            res = [(lambda r, kk=kk: (p_good if (kk == k_star and r.random() < pi) else 0.0))
                   for kk in range(K)]
            cfg = LexisConfig(alpha=ALPHA, eps=EPS, budget=200000, cap=30, audit_share=0.0, weights=w,
                              stop_on_confirm=True)
            slots = []
            for _ in range(150):
                rep = run_lexis(res, cfg, rng)
                slots.append(rep.slots_used)
            m = float(np.mean(slots))
            worst = max(worst, m)
            print(f"  {name:12s} findable level {k_star + 1}: mean slots to stop {m:9.1f}")
        out[name] = worst
    good = out["uniform"] <= out["cheap-first"]
    print(f"  worst case: uniform {out['uniform']:.1f} vs cheap-first {out['cheap-first']:.1f}  "
          f"{'PASS' if good else 'FAIL'}")
    return good


def main():
    rng = np.random.default_rng(SEED)
    print(f"seed={SEED} alpha={ALPHA} eps={EPS}")
    results = [check_validity(rng), check_wald(rng), check_certificates(rng), check_minimax(rng)]
    check_counterexamples(rng)
    print("ALL PROVEN-BOUND CHECKS PASS" if all(results) else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
