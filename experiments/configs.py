"""Stage-4 experiment configurations (preregistered in docs/stage4_experiments_and_validation.md)."""

import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.ledger import LedgerConfig  # noqa: E402
from fresco.sim.nodes import WorkerConfig  # noqa: E402
from fresco.sim.run import SimConfig, centralized, simulate, simulate_independent  # noqa: E402
from fresco.sim.scenario import Level, Scenario  # noqa: E402

WORKERS = (1, 2, 4, 8, 16, 32)
HORIZON = 150000.0

SCENARIOS = {
    "S1-moderate": Scenario(levels=(Level(), Level(), Level(pi=0.05), Level(pi=0.10))),
    "S2-sparse": Scenario(levels=(Level(), Level(), Level(pi=0.01), Level(pi=0.05))),
}

BASE = SimConfig(workers=1, horizon=HORIZON, stop_at_level=3,
                 ledger=LedgerConfig(max_slots=10**7),
                 worker=WorkerConfig(),
                 scenario=SCENARIOS["S1-moderate"])


def weak_scenario(w):
    """Weak scaling: the single findable level gets 1/W as many violators, so the
    expected search work grows proportionally to W."""
    return Scenario(levels=(Level(), Level(), Level(pi=0.16 / w), Level()))


# ---- picklable method wrappers -------------------------------------------------
def m_coop(cfg):
    return simulate(cfg)


def m_indep(cfg):
    return simulate_independent(cfg)


def m_central(cfg):
    return simulate(centralized(cfg))


METHODS = {"FRESCO (cooperative)": m_coop,
           "independent eps/W": m_indep,
           "centralized scheduler": m_central}


def with_(cfg, **kw):
    return replace(cfg, **kw)
