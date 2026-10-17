"""Stage-3 end-to-end fault injection: does the *implemented* protocol keep its
validity guarantee under realistic distributed faults, and does removing single
rules break it at system level (not only in the Stage-2 abstract model)?

Scenario: every candidate at every level is a null at the least-favourable
boundary p = alpha, so any confirmation is a false confirmation. Each unsafe
variant is paired with FRESCO under exactly the same fault triggers.

Synthetic oracle only; not evidence about LLM agents.

Run:  python3 -I sims/stage3_fault_injection.py [runs_per_config]   (default 60)
"""

import math
import multiprocessing as mp
import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.ledger import LedgerConfig  # noqa: E402
from fresco.sim.network import NetConfig  # noqa: E402
from fresco.sim.nodes import WorkerConfig  # noqa: E402
from fresco.sim.run import FaultSchedule, SimConfig, simulate  # noqa: E402
from fresco.sim.scenario import FaultModel, Level, Scenario  # noqa: E402

EPS = 0.05
NULL = tuple(Level(pi=0.0, null_at_boundary=True) for _ in range(4))
BASE = SimConfig(workers=4, horizon=40000.0,
                 ledger=LedgerConfig(eps=EPS, max_slots=3000, cap=120),
                 worker=WorkerConfig(audit_share=0.0, pool=2, lease_fraction=0.5, rotate_after=4),
                 scenario=Scenario(levels=NULL))

CRASHY = FaultModel(crash_benign=0.3, crash_violation=0.1)
FAST_VIOLATIONS = FaultModel(t_benign=30.0, t_violation=5.0)


def cfg_pair(name, trigger, unsafe_flag):
    safe = trigger(BASE)
    unsafe = replace(safe, ledger=replace(safe.ledger, **{unsafe_flag: True}))
    return [(f"{name} / FRESCO", safe), (f"{name} / without rule", unsafe)]


CONFIGS = (
    [("clean / FRESCO", BASE),
     ("all faults combined / FRESCO", replace(
         BASE,
         ledger=replace(BASE.ledger, slot_ttl=90.0),
         net=NetConfig(drop=0.1, duplicate=0.2, partitions=((800.0, 1600.0, frozenset({"w0", "w1"})),)),
         scenario=replace(BASE.scenario, faults=FaultModel(t_benign=30.0, t_violation=10.0,
                                                           crash_benign=0.3, crash_violation=0.1)),
         worker=replace(BASE.worker, executors=8, inflight_per_candidate=8),
         faults=FaultSchedule(worker_crash_rate=1 / 2000, ledger_crashes=(1200.0, 3000.0))))]
    + cfg_pair("R3 dedup (net duplicate 0.3)",
               lambda c: replace(c, net=NetConfig(duplicate=0.3)), "unsafe_no_dedup")
    + cfg_pair("R4 no fresh retry (crash 0.3/0.1)",
               lambda c: replace(c, scenario=replace(c.scenario, faults=CRASHY),
                                 ledger=replace(c.ledger, slot_ttl=90.0)), "unsafe_fresh_retry")
    + cfg_pair("R3 in-order (violations 6x faster, 8 in flight)",
               lambda c: replace(c, scenario=replace(c.scenario, faults=FAST_VIOLATIONS),
                                 worker=replace(c.worker, executors=8, inflight_per_candidate=8)),
               "unsafe_arrival_order")
    + cfg_pair("R5 global budget (W=8)",
               lambda c: replace(c, workers=8, ledger=replace(c.ledger, max_slots=6000)),
               "unsafe_local_budget")
)


def one(args):
    idx, seed = args
    name, cfg = CONFIGS[idx]
    r = simulate(replace(cfg, seed=seed))
    return idx, int(r["false_confirmations"] > 0), r["slots_leased"], r["ledger_stats"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    jobs = [(i, 1000 + s) for i in range(len(CONFIGS)) for s in range(runs)]
    with mp.Pool(min(mp.cpu_count(), 8)) as pool:
        out = pool.map(one, jobs, chunksize=4)
    print(f"eps={EPS}, runs per config={runs}, scenario: all candidates null at p = alpha = 0.2")
    print(f"{'configuration':62s} {'P(false conf.)':>14s}  {'95% Wilson CI':>17s}  {'mean slots':>10s}")
    for i, (name, _) in enumerate(CONFIGS):
        rows = [o for o in out if o[0] == i]
        k = sum(o[1] for o in rows)
        lo, hi = wilson(k, len(rows))
        slots = sum(o[2] for o in rows) / len(rows)
        flag = "" if "without rule" in name else ("  OK" if lo <= EPS else "  VIOLATION")
        print(f"{name:62s} {k / len(rows):14.3f}  [{lo:.3f}, {hi:.3f}]  {slots:10.0f}{flag}")


if __name__ == "__main__":
    main()
