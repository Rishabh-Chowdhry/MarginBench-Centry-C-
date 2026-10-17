import math
import pathlib
import sys
from dataclasses import replace

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from analysis.stats import censor, holm, kaplan_meier, mann_whitney, wilson  # noqa: E402
from fresco.baselines.alg1 import cp_lower, wilson_lower  # noqa: E402
from fresco.certificates import binom_tail  # noqa: E402
from fresco.ledger import LedgerConfig  # noqa: E402
from fresco.sim.run import SimConfig, centralized, simulate, simulate_independent  # noqa: E402


def test_cp_lower_is_exact():
    lo = cp_lower(18, 30, 0.01)
    assert math.isclose(binom_tail(30, lo, 18), 0.01, rel_tol=1e-6)
    assert cp_lower(0, 30, 0.05) == 0.0


def test_wilson_lower_less_conservative_than_cp_here():
    assert wilson_lower(18, 30, 0.05) > cp_lower(18, 30, 0.05)


def test_holm_matches_definition():
    adj = holm([0.01, 0.04, 0.03, 0.2])
    assert np.allclose(adj, [0.04, 0.09, 0.09, 0.2])


def test_mann_whitney_symmetry_and_sign():
    x, y = [1, 2, 3, 4], [5, 6, 7, 8]
    _, p, rbc = mann_whitney(x, y)
    assert rbc == 1.0 and p < 0.05
    _, p2, rbc2 = mann_whitney(y, x)
    assert rbc2 == -1.0 and math.isclose(p, p2)


def test_censor_and_km():
    v, e = censor([10, None, 30], 100)
    assert list(v) == [10, 100, 30] and list(e) == [True, False, True]
    t, s = kaplan_meier(v, e)
    assert list(t) == [0, 10, 30] and np.allclose(s, [1, 2 / 3, 1 / 3])


def test_wilson_interval_contains_p():
    p, lo, hi = wilson(5, 100)
    assert lo < p < hi


def test_baseline_runners():
    cfg = SimConfig(workers=4, seed=2, horizon=5000.0, stop_at_level=3, ledger=LedgerConfig(max_slots=10**6))
    a = simulate_independent(cfg)
    assert a["workers"] == 4 and a["false_confirmations"] == 0
    c = centralized(cfg)
    assert c.workers == 1 and c.worker.executors == 4 * cfg.worker.executors
    r = simulate(cfg)
    if r["time_final_frontier"] is not None:
        assert r["calls_until_final"] <= r["slots_leased"]
