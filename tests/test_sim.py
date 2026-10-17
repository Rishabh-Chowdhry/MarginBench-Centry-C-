import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.ledger import LedgerConfig  # noqa: E402
from fresco.sim.network import NetConfig  # noqa: E402
from fresco.sim.run import FaultSchedule, SimConfig, simulate  # noqa: E402
from fresco.sim.scenario import FaultModel, Level, Scenario  # noqa: E402

SMALL = SimConfig(workers=3, seed=5, horizon=3000.0, ledger=LedgerConfig(max_slots=3000))


def test_simulation_is_deterministic():
    a, b = simulate(SMALL), simulate(SMALL)
    assert a["trace_digest"] == b["trace_digest"] and a["ledger_digest"] == b["ledger_digest"]
    c = simulate(replace(SMALL, seed=6))
    assert c["trace_digest"] != a["trace_digest"]


def test_finds_true_margin_without_faults():
    r = simulate(replace(SMALL, workers=8, horizon=8000.0, ledger=LedgerConfig(max_slots=20000)))
    assert r["b_hat"] == r["k_star"] == 3
    assert r["false_confirmations"] == 0


def test_survives_combined_faults():
    cfg = replace(
        SMALL,
        horizon=6000.0,
        ledger=LedgerConfig(max_slots=8000, slot_ttl=90.0),
        net=NetConfig(drop=0.1, duplicate=0.2, partitions=((500.0, 900.0, frozenset({"w0"})),)),
        scenario=replace(Scenario(), faults=FaultModel(crash_benign=0.1, crash_violation=0.05)),
        faults=FaultSchedule(worker_crash_rate=1 / 1500, ledger_crashes=(700.0, 2500.0)),
    )
    r = simulate(cfg)                       # simulate() asserts ledger invariants at the end
    assert r["net"]["dropped"] > 0 and r["net"]["duplicated"] > 0 and r["net"]["partitioned"] > 0
    assert len(r["ledger_recoveries"]) == 2 and all(ok for *_, ok in r["ledger_recoveries"])
    assert r["ledger_stats"]["duplicate_requests"] > 0       # retries absorbed idempotently
    assert r["ledger_stats"]["expired_slots"] > 0            # executor crashes imputed
    assert r["false_confirmations"] == 0


def test_unsafe_no_dedup_applies_duplicates():
    cfg = replace(SMALL, ledger=LedgerConfig(max_slots=2000, unsafe_no_dedup=True),
                  net=NetConfig(duplicate=0.3))
    assert simulate(cfg)["ledger_stats"]["duplicates_applied"] > 0
    safe = simulate(replace(cfg, ledger=LedgerConfig(max_slots=2000)))
    assert safe["ledger_stats"]["duplicates_applied"] == 0 and safe["ledger_stats"]["duplicate_requests"] > 0


def test_boundary_null_scenario_has_no_k_star():
    sc = Scenario(levels=tuple(Level(pi=0.0, null_at_boundary=True) for _ in range(4)))
    assert sc.k_star() is None and all(sc.is_null(1, c) for c in range(20))
