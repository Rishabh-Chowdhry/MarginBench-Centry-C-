"""E7: calibration of the cost-level certificates (G2). Levels contain rare true
violators (mu_k > 0) that are hard to confirm, so the certificate must cover a
non-zero mass: coverage = P(eta_k >= mu_k for all k) must be >= 1 - eps_audit.

Run: python3 -I experiments/e7_certificates.py [seeds]   (default 200)
"""

import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from experiments.configs import BASE, m_coop  # noqa: E402
from fresco.sim.scenario import Level, Scenario  # noqa: E402

SC = Scenario(levels=(Level(pi=0.003, p_good=0.3), Level(pi=0.01, p_good=0.3), Level(), Level()))
C = replace(BASE, workers=4, horizon=6000.0, stop_at_level=0, scenario=SC,
            worker=replace(BASE.worker, audit_share=0.5))

VARIANTS = {
    "r=3, t=1, certify p>=0.2": C,
    "r=10, t=4, certify p>=0.3": replace(C, ledger=replace(C.ledger, audit_repeats=10, audit_threshold=4,
                                                            audit_level=0.3)),
}


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    jobs = [(m_coop, {"variant": name, "seed": s, "mu": [SC.mu(k) for k in range(1, 5)]}, replace(cfg, seed=s))
            for name, cfg in VARIANTS.items() for s in range(seeds)]
    run_jobs("e7_certificates", jobs)


if __name__ == "__main__":
    main()
