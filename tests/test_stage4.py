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


# ---- Stage 6: screening + LEXIS hybrid ------------------------------------------
from fresco.baselines.alg1 import Alg1Config, run_alg1_multipass  # noqa: E402
from fresco.eprocess import PriorKelly  # noqa: E402
from fresco.hybrid import HybridConfig, run_hybrid  # noqa: E402


def _res(pi3=0.05):
    def lvl(pi):
        return lambda r: 0.6 if r.random() < pi else r.uniform(0, 0.2)
    return [lvl(0), lvl(0), lvl(pi3), lvl(0.1)]


def test_prior_kelly_bets_in_range_and_prior_shifts_bet():
    s = PriorKelly(2.5, 0.0)
    for succ, n in ((0, 0), (0, 10), (10, 10)):
        lam = s(succ, n, 0.2)
        assert 0 <= lam < 1 / 0.2
    assert s(0, 0, 0.2) > PriorKelly(0.0, 2.5)(0, 0, 0.2)


def test_hybrid_deterministic_and_budget_respected():
    cfg = HybridConfig(budget=3000, stop_at_level=3)
    a = [run_hybrid(_res(), cfg, np.random.default_rng(4)) for _ in range(3)]
    b = [run_hybrid(_res(), cfg, np.random.default_rng(4)) for _ in range(3)]
    assert a == b and all(r["slots"] <= 3000 for r in a)
    r = run_alg1_multipass(_res(), Alg1Config(), np.random.default_rng(4), 3000, stop_at_level=3)
    assert r["slots"] <= 3000


def test_hybrid_single_pass_stays_within_one_pass_budget():
    cfg = HybridConfig()
    r = run_hybrid(_res(0.0), cfg, np.random.default_rng(1))
    assert r["slots"] <= 4 * (cfg.q * cfg.r_d + cfg.T * cfg.cap) and r["passes"] == 1


def test_hybrid_rarely_confirms_boundary_nulls():
    null = [lambda r: 0.2] * 4
    rng = np.random.default_rng(7)
    false = sum(run_hybrid(null, HybridConfig(), rng)["false"] for _ in range(300))
    assert false <= 6          # nominal 0.05 -> ~15 expected at the bound; observed far lower
