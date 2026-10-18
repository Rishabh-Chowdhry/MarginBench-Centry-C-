"""E8 (Stage 6): screening + LEXIS hybrid (LEXIS-S) vs repaired Algorithm 1.
Hypotheses are preregistered in docs/stage6_hybrid_screening_lexis.md.

Run: python3 -I experiments/e8_hybrid.py [reps]   (default 2000)
"""

import pathlib
import sys
import zlib

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from experiments.e4_alg1 import INSTANCES  # noqa: E402
from fresco.baselines.alg1 import Alg1Config, run_alg1, run_alg1_multipass  # noqa: E402
from fresco.hybrid import HybridConfig, run_hybrid  # noqa: E402

MULTI_BUDGET = 5000
DEFAULT = (40, 5, 3)
SWEEP = [(20, 5, 3), (40, 3, 3), (80, 5, 5)]


def one_run(method, params, res, rng):
    q, r_d, T = params
    if method == "alg1-cp":
        return run_alg1(res, Alg1Config(candidates_per_level=q, discovery_reps=r_d, top=T, rule="cp-KT"), rng)
    if method == "alg1-cp-multipass":
        return run_alg1_multipass(res, Alg1Config(candidates_per_level=q, discovery_reps=r_d, top=T),
                                  rng, MULTI_BUDGET, stop_at_level=3)
    cfg = HybridConfig(q=q, r_d=r_d, T=T, cap=30)
    if method == "lexis-s":
        return run_hybrid(res, cfg, rng)
    if method == "lexis-s-uniform":
        cfg.weighting = "uniform"
        return run_hybrid(res, cfg, rng)
    if method == "lexis-s-multipass":
        cfg.budget, cfg.stop_at_level = MULTI_BUDGET, 3
        return run_hybrid(res, cfg, rng)
    raise ValueError(method)


def job(args):
    inst, method, params, chunk, reps = args
    rng = np.random.default_rng([chunk, zlib.crc32(method.encode()), zlib.crc32(inst.encode()),
                                 zlib.crc32(repr(params).encode()), 8])
    res = INSTANCES[inst]()
    rows = []
    for _ in range(reps):
        r = one_run(method, params, res, rng)
        rows.append((r["b_hat"], r["slots"], r["false"]))
    return {"rows": rows}


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    chunks = 20
    cells = []
    for inst in INSTANCES:
        for m in ("alg1-cp", "lexis-s", "lexis-s-uniform", "alg1-cp-multipass", "lexis-s-multipass"):
            cells.append((inst, m, DEFAULT))
        if inst != "null-boundary":
            for p in SWEEP:
                for m in ("alg1-cp", "lexis-s"):
                    cells.append((inst, m, p))
        else:
            for p in SWEEP:
                cells.append((inst, "lexis-s", p))
    jobs = [(job, {"instance": i, "method": m, "params": list(p), "chunk": c}, (i, m, p, c, reps // chunks))
            for i, m, p in cells for c in range(chunks)]
    run_jobs("e8_hybrid", jobs)


if __name__ == "__main__":
    main()
