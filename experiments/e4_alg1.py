"""E4 (H-vs-Alg1): LEXIS vs the manuscript's Algorithm 1 at the slot level
(single process, no distribution), on (a) a boundary-null instance for
validity and (b) the S1/S2 reservoirs for efficiency.

Run: python3 -I experiments/e4_alg1.py [reps]   (default 2000)
"""

import pathlib
import sys
import zlib

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from fresco.baselines.alg1 import Alg1Config, run_alg1  # noqa: E402
from fresco.lexis import LexisConfig, run_lexis  # noqa: E402

ALPHA = 0.2


def reservoir(pi, p_good=0.6, boundary=False):
    def draw(rng):
        if rng.random() < pi:
            return p_good
        return ALPHA if boundary else rng.uniform(0, ALPHA)
    return draw


INSTANCES = {
    "null-boundary": lambda: [reservoir(0.0, boundary=True)] * 4,
    "S1-moderate": lambda: [reservoir(0), reservoir(0), reservoir(0.05), reservoir(0.10)],
    "S2-sparse": lambda: [reservoir(0), reservoir(0), reservoir(0.01), reservoir(0.05)],
}
ALG1_BUDGET = 4 * (40 * 5 + 3 * 30)   # Algorithm 1's maximum slot use (one pass)


def job(args):
    inst, method, seed, reps = args
    rng = np.random.default_rng([seed, zlib.crc32(method.encode()), zlib.crc32(inst.encode())])
    res = INSTANCES[inst]()
    out = []
    for _ in range(reps):
        if method.startswith("alg1"):
            r = run_alg1(res, Alg1Config(rule=method.split(":")[1]), rng)
            out.append((r["b_hat"], r["slots"], r["false"]))
        else:
            budget = ALG1_BUDGET if method == "lexis:matched" else 30000
            cfg = LexisConfig(alpha=ALPHA, budget=budget, audit_share=0.0, stop_at_level=3)
            rep = run_lexis(res, cfg, rng)
            false = any(p <= ALPHA for _, p, _ in rep.confirmations)
            b = None if rep.b_hat == float("inf") else rep.b_hat
            out.append((b, rep.slots_used, false))
    return {"rows": out}


def wrapped(cfg):
    return job(cfg)


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    chunks = 20
    jobs = []
    for inst in INSTANCES:
        for method in ("alg1:wilson-T", "alg1:cp-KT", "lexis:matched", "lexis:open"):
            for c in range(chunks):
                jobs.append((wrapped, {"instance": inst, "method": method, "chunk": c},
                             (inst, method, c, reps // chunks)))
    run_jobs("e4_alg1", jobs)


if __name__ == "__main__":
    main()
