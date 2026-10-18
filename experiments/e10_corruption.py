"""E10 (preregistered in docs/stage7_quintet_hkg_twgr.md §6): TWGR repair of the
QUINTET heterogeneous knowledge graph under independent storage corruption, with
ablations and baselines; plus whole-domain loss.

One QUINTET run per (scenario, seed). The same corrupted fabric (same rng) is given
to every variant, so variant comparisons are paired.

Run: python3 -I experiments/e10_corruption.py [runs]   (default 40)
"""

import copy
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from fresco.hkg.corrupt import corrupt_fabric  # noqa: E402
from fresco.hkg.graph import DOMAINS, DomainStore  # noqa: E402
from fresco.hkg.repair import QUARANTINED, RunParams, TWGRConfig, report, twgr  # noqa: E402
from fresco.quintet.cluster import Quintet, QuintetConfig  # noqa: E402
from fresco.sim.scenario import Level, Scenario  # noqa: E402

RHOS = (0.0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6)
LOSSES = (1, 2, 3)
EPS = 0.05
SCENARIOS = {
    "S1-dense": Scenario(levels=(Level(), Level(), Level(pi=0.3), Level(pi=0.5))),
    "boundary-null": Scenario(levels=tuple(Level(null_at_boundary=True) for _ in range(4))),
}
PARAMS = RunParams(eps=EPS, lease_size=8, run_key=b"e10-run-key", alpha=0.2, cap=40)

VARIANTS = {
    "TWGR": TWGRConfig(),
    "-replicas": TWGRConfig(use_replicas=False),
    "-log anchors": TWGRConfig(use_log_anchors=False),
    "-edge anchors": TWGRConfig(use_edge_anchors=False),
    "-derivation": TWGRConfig(use_derivation=False),
    "item votes": TWGRConfig(domain_votes=False),
    "replica-majority": TWGRConfig(copy_votes=True, use_log_anchors=False, use_edge_anchors=False,
                                   use_derivation=False, min_support=1),
    "best-effort": TWGRConfig(quarantine=False),
    # exploratory (added after the pilot, not preregistered): availability knob
    "TWGR support-1": TWGRConfig(min_support=1),
}
# one coordinator: one copy and one checksum log per record, nothing else to repair from
SINGLE = ("single-coordinator", TWGRConfig(use_edge_anchors=False, use_derivation=False, min_support=1))


def base_run(scenario, seed, replicas):
    q = Quintet(SCENARIOS[scenario], PARAMS, QuintetConfig(workers=4, budget=3000, crash=0.02, replicas=replicas),
                np.random.default_rng(seed))
    if replicas == 0:
        q.fabric.archivist_anchor = q.fabric.receipts = False
    q.run()
    return q


def score(q, fab, status, acc, scenario):
    truth = fab.truth
    sc = SCENARIOS[scenario]
    true_conf = {k for _, k in q.truth_report()["confirmed"]}
    rep = report(acc)
    got_conf = {k for _, k in rep["confirmed"]}
    nonconf = [i for i in truth if i[0] != "Confirmation"]
    wrong = sum(1 for i in nonconf if i in acc and acc[i].encode() != truth[i])
    correct = sum(1 for i in truth if i in acc and acc[i].encode() == truth[i])
    false_conf = 0
    for _, k in rep["confirmed"]:
        cand = q.nodes[("Candidate", k)].payload
        false_conf += int(sc.is_null(cand["level"], cand["content"]))
    return {"records": len(truth), "correct": correct, "recovery": correct / len(truth),
            "wrong_nonconf": wrong,
            "wrong_conf": sum(1 for i in truth if i[0] == "Confirmation" and i in acc and acc[i].encode() != truth[i]),
            "quarantined": sum(1 for s in status.values() if s == QUARANTINED),
            "phantoms": sum(1 for i in acc if i not in truth),
            "added_conf": len(got_conf - true_conf), "lost_conf": len(true_conf - got_conf),
            "false_conf": false_conf, "any_false_conf": int(false_conf > 0),
            "b_hat": rep["b_hat"], "b_hat_true": q.truth_report()["b_hat"],
            "b_hat_ok": int(rep["b_hat"] == q.truth_report()["b_hat"]), "k_star": sc.k_star()}


def one(cfg):
    scenario, seed = cfg["scenario"], cfg["seed"]
    rows = []
    q = base_run(scenario, seed, 2)
    q1 = base_run(scenario, seed, 0)
    for rho in RHOS:
        rng_seed = seed * 1000 + int(rho * 100)
        fab0 = copy.deepcopy(q.fabric)
        corrupt_fabric(fab0, rho, np.random.default_rng(rng_seed))
        for name, vcfg in VARIANTS.items():
            fab = copy.deepcopy(fab0)
            status, acc = twgr(fab, PARAMS, vcfg)
            rows.append({"study": "rho", "variant": name, "rho": rho, **score(q, fab, status, acc, scenario)})
        fab = copy.deepcopy(q1.fabric)
        corrupt_fabric(fab, rho, np.random.default_rng(rng_seed))
        status, acc = twgr(fab, PARAMS, SINGLE[1])
        rows.append({"study": "rho", "variant": SINGLE[0], "rho": rho, **score(q1, fab, status, acc, scenario)})
    lose_rng = np.random.default_rng(seed + 77)
    for k in LOSSES:
        lost = list(lose_rng.choice(DOMAINS, size=k, replace=False))
        for name in ("TWGR", "TWGR support-1", "replica-majority"):
            fab = copy.deepcopy(q.fabric)
            for d in lost:
                fab.stores[d] = DomainStore(d)
            status, acc = twgr(fab, PARAMS, VARIANTS[name])
            rows.append({"study": "loss", "variant": name, "lost": k, "lost_domains": lost,
                         **score(q, fab, status, acc, scenario)})
    return {"rows": rows}


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    jobs = [(one, {"scenario": s, "seed": r}, {"scenario": s, "seed": 10_000 + r})
            for s in SCENARIOS for r in range(runs)]
    run_jobs("e10_corruption", jobs)
