"""E6: fault-recovery timelines at W = 8: oracle-call throughput per 20 s bucket
around a ledger crash, a crash of half the workers, and a partition of half the
workers, compared with an unfaulted run on the same seeds.

Run: python3 -I experiments/e6_recovery.py [seeds]   (default 30)
"""

import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from experiments.configs import BASE, m_coop  # noqa: E402
from fresco.sim.network import NetConfig  # noqa: E402
from fresco.sim.run import FaultSchedule  # noqa: E402

T_FAULT = 1000.0
R = replace(BASE, workers=8, horizon=3000.0, stop_at_level=0, series_bucket=20.0)

VARIANTS = {
    "no fault": R,
    "ledger crash (60 s down)": replace(R, faults=FaultSchedule(ledger_crashes=(T_FAULT,), ledger_downtime=60.0)),
    "4 of 8 workers crash (120 s down)": replace(R, faults=FaultSchedule(
        worker_crashes=tuple((T_FAULT, i, 120.0) for i in range(4)))),
    "4 of 8 workers partitioned (300 s)": replace(R, net=NetConfig(
        partitions=((T_FAULT, T_FAULT + 300.0, frozenset({"w0", "w1", "w2", "w3"})),))),
}


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    jobs = [(m_coop, {"variant": name, "seed": s}, replace(cfg, seed=s))
            for name, cfg in VARIANTS.items() for s in range(seeds)]
    run_jobs("e6_recovery", jobs)


if __name__ == "__main__":
    main()
