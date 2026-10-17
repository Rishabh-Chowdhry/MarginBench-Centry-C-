"""Build and run one simulated FRESCO deployment; return metrics with ground truth."""

import hashlib
import json
from dataclasses import asdict, dataclass, field

from fresco.ledger import LedgerConfig
from fresco.sim.engine import Engine
from fresco.sim.network import NetConfig, Network
from fresco.sim.nodes import LEDGER, LedgerNode, Worker, WorkerConfig
from fresco.sim.scenario import Scenario


@dataclass(frozen=True)
class FaultSchedule:
    worker_crash_rate: float = 0.0     # crashes per worker per second (Poisson)
    worker_downtime: float = 30.0
    ledger_crashes: tuple = ()         # times at which the ledger crashes
    ledger_downtime: float = 20.0


@dataclass(frozen=True)
class SimConfig:
    workers: int = 4
    seed: int = 0
    horizon: float = 20000.0
    ledger: LedgerConfig = field(default_factory=LedgerConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    net: NetConfig = field(default_factory=NetConfig)
    scenario: Scenario = field(default_factory=Scenario)
    faults: FaultSchedule = field(default_factory=FaultSchedule)

    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:16]


def simulate(cfg):
    if cfg.ledger.levels != len(cfg.scenario.levels) or cfg.ledger.alpha != cfg.scenario.alpha:
        raise ValueError("ledger and scenario disagree on levels or alpha")
    eng = Engine(cfg.seed)
    net = Network(eng, cfg.net)
    names = [f"w{i}" for i in range(cfg.workers)]
    run_key = hashlib.sha256(f"run-key|{cfg.seed}".encode()).digest()
    node = LedgerNode(eng, net, cfg.ledger, run_key, names)
    workers = [Worker(eng, net, n, cfg.worker, cfg.ledger, cfg.scenario) for n in names]

    frng = eng.rng("faults")
    if cfg.faults.worker_crash_rate > 0:
        for w in workers:
            t = frng.exponential(1 / cfg.faults.worker_crash_rate)
            while t < cfg.horizon:
                eng.at(t, w.crash, cfg.faults.worker_downtime)
                t += frng.exponential(1 / cfg.faults.worker_crash_rate)
    for t in cfg.faults.ledger_crashes:
        eng.at(t, node.crash, cfg.faults.ledger_downtime)

    end = eng.run(cfg.horizon)
    if node.ledger is None:            # horizon reached while the ledger was down
        node.recover_now()
    led = node.ledger
    rep = led.report()
    sc = cfg.scenario
    false_conf = sum(1 for j, level, _, _ in led.confirmations
                     if sc.is_null(level, led.candidates[j]["content"]))
    first = min((t for *_, t in led.confirmations), default=None)
    final_t = next((t for j, level, _, t in led.confirmations if j == led.witness), None)
    led.check_invariants()
    return {
        "config_digest": cfg.digest(),
        "seed": cfg.seed,
        "workers": cfg.workers,
        "b_hat": rep["b_hat"],
        "k_star": sc.k_star(),
        "false_confirmations": false_conf,
        "confirmations": len(led.confirmations),
        "time_first_confirmation": first,
        "time_final_frontier": final_t,
        "end_time": end,
        "slots_leased": rep["slots_leased"],
        "executions": sum(w.executions for w in workers),
        "registrations": rep["registrations"],
        "certificates": rep["certificates"],
        "ledger_stats": rep["stats"],
        "worker_crashes": sum(w.crashes for w in workers),
        "ledger_recoveries": node.recoveries,
        "net": asdict(net.stats),
        "events": eng.events_run,
        "trace_digest": eng.trace_digest(),
        "ledger_digest": led.digest(),
    }
