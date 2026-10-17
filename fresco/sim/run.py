"""Build and run one simulated FRESCO deployment; return metrics with ground truth."""

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace

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
    worker_crashes: tuple = ()         # explicit ((time, worker_index, downtime), ...)


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
    stop_at_level: int = 1             # stop measurement once b_hat <= this level (use k* for time-to-k*)
    series_bucket: float = 0.0         # > 0: also return oracle calls per time bucket

    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:16]


def simulate(cfg):
    return simulate_full(cfg)[0]


def simulate_full(cfg):
    if cfg.ledger.levels != len(cfg.scenario.levels) or cfg.ledger.alpha != cfg.scenario.alpha:
        raise ValueError("ledger and scenario disagree on levels or alpha")
    eng = Engine(cfg.seed)
    net = Network(eng, cfg.net)
    names = [f"w{i}" for i in range(cfg.workers)]
    run_key = hashlib.sha256(f"run-key|{cfg.seed}".encode()).digest()
    node = LedgerNode(eng, net, cfg.ledger, run_key, names, stop_at_level=cfg.stop_at_level)
    workers = [Worker(eng, net, n, cfg.worker, cfg.ledger, cfg.scenario) for n in names]

    frng = eng.rng("faults")
    if cfg.faults.worker_crash_rate > 0:
        for w in workers:
            t = frng.exponential(1 / cfg.faults.worker_crash_rate)
            while t < cfg.horizon:
                eng.at(t, w.crash, cfg.faults.worker_downtime)
                t += frng.exponential(1 / cfg.faults.worker_crash_rate)
    for t, idx, down in cfg.faults.worker_crashes:
        eng.at(t, workers[idx].crash, down)
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
    leased_cand = sum(c["next_new"] - 1 for c in led.candidates.values()) + \
        sum(s["attempt"] for s in led.slots.values())
    consumed = sum(c["ep"].trials for c in led.candidates.values())
    out = {
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
        "calls_until_final": led.calls_until(final_t) if final_t is not None else None,
        "unconsumed_candidate_slots": leased_cand - consumed,
        "candidate_slots": leased_cand,
        "ledger_ops": len(led.journal),
    }
    if cfg.series_bucket > 0:
        import numpy as np
        edges = np.arange(0.0, end + cfg.series_bucket, cfg.series_bucket)
        out["series"] = np.histogram(led.lease_times, bins=edges)[0].tolist()
    return out, led


def derived_seed(seed, i):
    return int.from_bytes(hashlib.sha256(f"indep|{seed}|{i}".encode()).digest()[:4], "big")


def simulate_independent(cfg):
    """Baseline B1: W independent single-worker deployments, each with its own
    ledger and error budget eps / W (valid by a union bound over runs), each with
    the same per-worker executor count. Combined b_hat(t) = min over runs."""
    W = cfg.workers
    runs = []
    horizon = cfg.horizon
    for i in range(W):
        # Simulating run i past the earliest time any earlier run reached the target
        # cannot change the combined result (min over runs, calls counted up to t*).
        sub = replace(cfg, workers=1, seed=derived_seed(cfg.seed, i), horizon=horizon,
                      ledger=replace(cfg.ledger, eps=cfg.ledger.eps / W,
                                     max_slots=max(1, cfg.ledger.max_slots // W)))
        r, led = simulate_full(sub)
        runs.append((r, led))
        if r["b_hat"] is not None and r["b_hat"] <= cfg.stop_at_level and r["time_final_frontier"] is not None:
            horizon = min(horizon, r["time_final_frontier"])
    finals = [(r["b_hat"], r["time_final_frontier"]) for r, _ in runs if r["b_hat"] is not None]
    b_hat = min((b for b, _ in finals), default=None)
    t_star = min((t for b, t in finals if b == b_hat), default=None)
    calls = sum(led.calls_until(t_star) for _, led in runs) if t_star is not None else None
    return {
        "seed": cfg.seed, "workers": W, "b_hat": b_hat, "k_star": cfg.scenario.k_star(),
        "false_confirmations": sum(r["false_confirmations"] for r, _ in runs),
        "time_final_frontier": t_star, "calls_until_final": calls,
        "slots_leased": sum(r["slots_leased"] for r, _ in runs),
        "end_time": max(r["end_time"] for r, _ in runs),
    }


def centralized(cfg):
    """Baseline B4: one scheduler process owning all W x executors (same total concurrency)."""
    w = cfg.worker
    return replace(cfg, workers=1, worker=replace(w, executors=w.executors * cfg.workers,
                                                  pool=w.pool * cfg.workers,
                                                  lease_fraction=min(1.0, w.lease_fraction * cfg.workers)))
