"""Stage-1 sanity check: do common distributed-execution defaults break the
validity of sequential (e-process) confirmation of an attack candidate?

This is a pilot Monte Carlo check of the counterexamples stated in
docs/stage1_novelty_and_directions.md (Section 4.3). It uses a synthetic
Bernoulli oracle, not an LLM. It is NOT an experimental result about agents.

Null hypothesis for one candidate: p <= alpha (the candidate does NOT reach the
success threshold). We simulate at the boundary p = alpha, the least favourable
null, and count how often each accounting rule falsely "confirms" the candidate.

Run:  python3 -I sims/stage1_counterexamples.py
"""

import numpy as np

ALPHA = 0.2          # success-probability threshold defining the margin
EPS = 0.05           # target false-confirmation probability
LAM = 1.0            # fixed predictable betting fraction, must be in [0, 1/ALPHA)
N_SLOTS = 600        # trials per candidate before the run is abandoned
REPS = 20_000        # Monte Carlo replications
SEED = 20261017


def false_confirm_rate(y, weights=None):
    """Fraction of replications whose betting e-process ever crosses 1/EPS.

    y: (REPS, N) array of recorded outcomes in the order they are applied.
    weights: optional (REPS, N) multiplicity of each applied outcome (models
             duplicate delivery: a result applied twice contributes its factor twice).
    """
    log_factor = np.log1p(LAM * (y - ALPHA))
    if weights is not None:
        log_factor = log_factor * weights
    log_e = np.cumsum(log_factor, axis=1)
    return float(np.mean(log_e.max(axis=1) >= np.log(1.0 / EPS)))


def wilson_halfwidth(p, n=REPS):
    return 1.96 * np.sqrt(p * (1 - p) / n)


def main():
    rng = np.random.default_rng(SEED)
    p = ALPHA
    y = (rng.random((REPS, N_SLOTS)) < p).astype(float)
    rows = []

    # R0: slot-indexed, exactly-once, in-order commit (the proposed rule).
    rows.append(("exactly-once, slot-indexed (proposed)", false_confirm_rate(y)))

    # C1: at-least-once delivery, each result redelivered with prob 0.3 and the
    # naive accumulator applies it again.
    dup = 1.0 + (rng.random((REPS, N_SLOTS)) < 0.3)
    rows.append(("at-least-once, no dedup (dup prob 0.3)", false_confirm_rate(y, dup)))

    # C2: outcome-correlated crashes + fresh-seed retry. Non-violating
    # trajectories crash/time out with prob C0 (e.g. long benign trajectories hit
    # the time limit), violating ones with prob C1 < C0, and crashed trials are
    # silently re-run with a new seed. The applied stream then has success prob
    # p(1-C1) / (p(1-C1) + (1-p)(1-C0)) > alpha.
    c0, c1 = 0.3, 0.1
    p_eff = p * (1 - c1) / (p * (1 - c1) + (1 - p) * (1 - c0))
    y_retry = (rng.random((REPS, N_SLOTS)) < p_eff).astype(float)
    rows.append((f"crash->fresh retry (applied p={p_eff:.3f})", false_confirm_rate(y_retry)))

    # R3: same crashes, but a crashed slot is recorded as Y=0 and never retried
    # (direction-aware conservative imputation for confirmation).
    u = rng.random((REPS, N_SLOTS))
    crashed = np.where(y == 1, u < c1, u < c0)
    y_cons = np.where(crashed, 0.0, y)
    rows.append(("crash->Y=0, no retry (proposed)", false_confirm_rate(y_cons)))

    # C3: W workers each run a local level-EPS test on its own null candidate
    # (worker-local error control, no shared budget). Family-wise error over W.
    for w in (2, 8, 32):
        per = false_confirm_rate((rng.random((REPS // 4, N_SLOTS)) < p).astype(float))
        fwer = 1 - (1 - per) ** w
        rows.append((f"worker-local level eps, W={w} (FWER)", fwer))

    # R4: escrowed budget, eps/W per candidate, W=32 independent null
    # candidates simulated jointly; FWER = P(any candidate falsely confirmed).
    w = 32
    yy = (rng.random((REPS // 4, w, N_SLOTS)) < p).astype(float)
    log_e = np.cumsum(np.log1p(LAM * (yy - ALPHA)), axis=2)
    fwer = float(np.mean((log_e.max(axis=2) >= np.log(w / EPS)).any(axis=1)))
    rows.append((f"escrowed eps/W, W={w} (FWER)", fwer))

    print(f"alpha={ALPHA} eps={EPS} lambda={LAM} slots={N_SLOTS} reps={REPS} seed={SEED}")
    print(f"{'accounting rule':48s} false-confirm   +/-95%")
    for name, r in rows:
        print(f"{name:48s} {r:10.4f}   {wilson_halfwidth(r):.4f}")


if __name__ == "__main__":
    main()
