import math
import sys
import pathlib

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco import (BernoulliUpperCS, BudgetLedger, EProcess, FixedBet, PlugInKelly,  # noqa: E402
                    mass_bound, polynomial_weight, zero_failure_upper)
from fresco.eprocess import kl_bernoulli, log_growth  # noqa: E402
from fresco.lexis import LexisConfig, run_lexis  # noqa: E402
from fresco.spending import BudgetError  # noqa: E402


def test_bet_outside_range_rejected():
    ep = EProcess(0.2, FixedBet(5.0))  # 1/alpha = 5 is not allowed
    with pytest.raises(ValueError):
        ep.update(1)


def test_strategy_sees_only_committed_prefix():
    seen = []

    def spy(successes, trials, alpha):
        seen.append((successes, trials))
        return 1.0

    ep = EProcess(0.2, spy)
    for y in (1, 0, 1, 1):
        ep.update(y)
    assert seen == [(0, 0), (1, 1), (1, 2), (2, 3)]


def test_eprocess_value_matches_product():
    ep = EProcess(0.2, FixedBet(1.0))
    ys = [1, 0, 0, 1, 1]
    for y in ys:
        ep.update(y)
    expected = math.prod(1 + 1.0 * (y - 0.2) for y in ys)
    assert math.isclose(math.exp(ep.log_e), expected)


def test_kelly_growth_equals_kl():
    alpha, p1 = 0.2, 0.45
    bet = FixedBet.kelly(alpha, p1)
    assert math.isclose(log_growth(bet.lam, alpha, p1), kl_bernoulli(p1, alpha), rel_tol=1e-12)


def test_plugin_bet_in_range():
    s = PlugInKelly()
    for succ in range(0, 50, 7):
        lam = s(succ, 50, 0.2)
        assert 0 <= lam < 1 / 0.2


def test_polynomial_weights_sum_to_eps():
    eps = 0.05
    total = sum(polynomial_weight(j, eps) for j in range(1, 200001))
    assert total < eps and math.isclose(total, eps, rel_tol=1e-4)


def test_ledger_invariants_random_ops():
    rng = np.random.default_rng(0)
    led = BudgetLedger(0.05)
    open_leases = []
    cid = 0
    for _ in range(2000):
        op = rng.integers(3)
        try:
            if op == 0:
                open_leases.append(led.grant(float(rng.uniform(0, 0.01))))
            elif op == 1 and open_leases:
                cid += 1
                led.register(open_leases[rng.integers(len(open_leases))], cid)
            elif op == 2 and open_leases:
                led.close(open_leases.pop(rng.integers(len(open_leases))))
        except BudgetError:
            pass
        led.check_invariant()


def test_closed_lease_is_fenced():
    led = BudgetLedger(0.05)
    lid = led.grant(0.01)
    led.register(lid, "a")
    led.close(lid)
    with pytest.raises(BudgetError):
        led.register(lid, "b")


def test_duplicate_registration_rejected():
    led = BudgetLedger(0.05)
    lid = led.grant(0.01)
    led.register(lid, "a")
    with pytest.raises(BudgetError):
        led.register(lid, "a")


def test_zero_failure_bound():
    assert zero_failure_upper(0, 0.05) == 1.0
    n = 100
    u = zero_failure_upper(n, 0.05)
    assert math.isclose((1 - u) ** n, 0.05)
    assert u <= math.log(1 / 0.05) / n


def test_mass_bound_monotone_in_repeats():
    assert mass_bound(0.01, 0.2, 5) < mass_bound(0.01, 0.2, 1)


def test_cs_upper_shrinks_on_zeros_and_stays_in_unit_interval():
    cs = BernoulliUpperCS(0.05, grid_size=200)
    ups = []
    for _ in range(300):
        cs.update(0)
        ups.append(cs.upper())
    assert all(0 < u <= 1 for u in ups)
    assert ups[-1] < 0.05


def test_lexis_deterministic_given_seed():
    res = [lambda r: 0.0, lambda r: (0.6 if r.random() < 0.1 else 0.1)]
    cfg = LexisConfig(budget=2000)
    a = run_lexis(res, cfg, np.random.default_rng(7))
    b = run_lexis(res, cfg, np.random.default_rng(7))
    assert a == b


def test_lexis_prunes_levels_at_or_above_frontier():
    res = [lambda r: 0.0, lambda r: 0.9, lambda r: 0.9]
    rep = run_lexis(res, LexisConfig(budget=4000, audit_share=0.0), np.random.default_rng(3))
    assert rep.b_hat == 2
    # after the first confirmation at level 2, nothing at level >= 2 is confirmed again
    first = next(i for i, c in enumerate(rep.confirmations) if c[0] == 2)
    assert all(c[0] < 2 for c in rep.confirmations[first + 1:])
