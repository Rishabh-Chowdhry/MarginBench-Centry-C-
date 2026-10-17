"""E2/E3: strong scaling, weak scaling, communication overhead, and H-coop
(cooperative FRESCO vs W independent eps/W runs vs one centralized scheduler).

Run: python3 -I experiments/e2_scaling.py [seeds]   (default 100)
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from experiments.configs import BASE, METHODS, SCENARIOS, WORKERS, m_coop, weak_scenario, with_  # noqa: E402


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    jobs = []
    for sc_name, sc in SCENARIOS.items():
        for W in WORKERS:
            for m_name, fn in METHODS.items():
                if W == 1 and m_name != "FRESCO (cooperative)":
                    continue  # identical to cooperative at W = 1
                for s in range(seeds):
                    cfg = with_(BASE, workers=W, seed=s, scenario=sc)
                    jobs.append((fn, {"exp": "strong", "scenario": sc_name, "method": m_name, "W": W, "seed": s}, cfg))
    for W in WORKERS:
        for s in range(seeds):
            cfg = with_(BASE, workers=W, seed=10_000 + s, scenario=weak_scenario(W))
            jobs.append((m_coop, {"exp": "weak", "scenario": f"weak-pi={0.16 / W:.4f}",
                                  "method": "FRESCO (cooperative)", "W": W, "seed": s}, cfg))
    jobs.sort(key=lambda j: -j[1]["W"])  # long jobs first for load balance
    run_jobs("e2_scaling", jobs)


if __name__ == "__main__":
    main()
