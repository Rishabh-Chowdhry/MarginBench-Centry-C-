"""E1: validity of every distributed method on the boundary-null instance
(every confirmation is false). Complements sims/stage3_fault_injection.py
(rule ablations) and experiments/e4_alg1.py (Algorithm 1).

Run: python3 -I experiments/e1_validity.py [seeds]   (default 400)
"""

import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from experiments.configs import BASE, METHODS  # noqa: E402
from fresco.sim.scenario import Level, Scenario  # noqa: E402

NULL = Scenario(levels=tuple(Level(pi=0.0, null_at_boundary=True) for _ in range(4)))
V = replace(BASE, horizon=40000.0, stop_at_level=0, scenario=NULL,
            ledger=replace(BASE.ledger, max_slots=4000, cap=120),
            worker=replace(BASE.worker, audit_share=0.0))


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    jobs = []
    for W in (1, 8, 32):
        for m_name, fn in METHODS.items():
            if W == 1 and m_name != "FRESCO (cooperative)":
                continue
            for s in range(seeds):
                jobs.append((fn, {"method": m_name, "W": W, "seed": s}, replace(V, workers=W, seed=50_000 + s)))
    run_jobs("e1_validity", jobs)


if __name__ == "__main__":
    main()
