"""E5: component ablations and sensitivity at W = 8 on S1-moderate (and the lease
policy also at W = 32). Every variant is valid by Theorem 8; only efficiency changes.

Run: python3 -I experiments/e5_ablations.py [seeds]   (default 80)
"""

import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from experiments.configs import BASE, m_coop  # noqa: E402
from fresco.sim.scenario import FaultModel  # noqa: E402

B8 = replace(BASE, workers=8)


def wk(c, **kw):
    return replace(c, worker=replace(c.worker, **kw))


def lg(c, **kw):
    return replace(c, ledger=replace(c.ledger, **kw))


CRASH = FaultModel(crash_benign=0.2, crash_violation=0.2)

VARIANTS = {
    "default (poly lease R=8, m=2, pool=2, audit 0.1, cap 60)": B8,
    "lease policy: fraction 1/16 (Stage 3)": lg(B8, lease_policy="fraction"),
    "lease policy: fraction 1/16, W=32": replace(lg(B8, lease_policy="fraction"), workers=32),
    "default, W=32": replace(B8, workers=32),
    "lease size R=2": lg(B8, lease_size=2),
    "lease size R=32": lg(B8, lease_size=32),
    "in-flight m=1": wk(B8, inflight_per_candidate=1),
    "in-flight m=4 (executors 4)": wk(B8, inflight_per_candidate=4),
    "pool=1": wk(B8, pool=1),
    "pool=8": wk(B8, pool=8),
    "audit share 0": wk(B8, audit_share=0.0),
    "audit share 0.3": wk(B8, audit_share=0.3),
    "cap 30": lg(B8, cap=30),
    "cap 120": lg(B8, cap=120),
    "cheap-first level weights": wk(B8, level_weights=(0.55, 0.25, 0.12, 0.08)),
    "executor crash 0.2, async (crash -> Y=0)": replace(B8, scenario=replace(B8.scenario, faults=CRASH)),
    "executor crash 0.2, replay (same key)": lg(replace(B8, scenario=replace(B8.scenario, faults=CRASH)),
                                               mode="replay"),
}


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    jobs = [(m_coop, {"variant": name, "seed": s}, replace(cfg, seed=s))
            for name, cfg in VARIANTS.items() for s in range(seeds)]
    run_jobs("e5_ablations", jobs)


if __name__ == "__main__":
    main()
