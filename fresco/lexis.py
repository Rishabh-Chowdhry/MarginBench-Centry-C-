"""Single-process LEXIS (Algorithm 1 in the Stage 2 doc) over a synthetic oracle.

A synthetic instance is a list of K reservoirs: reservoir k (cost level k+1)
returns the violation probability p of a freshly generated candidate. The
oracle for a slot of candidate j is Bernoulli(p_j). This is an executable
specification used to check the propositions; it is not an LLM harness.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from fresco.certificates import BernoulliUpperCS, mass_bound, zero_failure_upper
from fresco.eprocess import EProcess, PlugInKelly
from fresco.spending import polynomial_weight


@dataclass
class LexisConfig:
    alpha: float = 0.2
    eps: float = 0.05          # confirmation error budget (upper side)
    eps_audit: float = 0.05    # certificate error budget (lower side)
    cap: int = 60              # max slots per candidate before abandonment
    audit_share: float = 0.1   # fraction of scheduling decisions spent on audit draws
    audit_repeats: int = 3     # r: runs per audit draw
    budget: int = 5000         # total oracle calls (slots)
    weights: tuple = None      # per-level scheduling weights; None = uniform
    strategy: object = field(default_factory=PlugInKelly)
    stop_on_confirm: bool = False  # stop at the first confirmation (for time-to-first checks)
    stop_at_level: int = 0         # stop once b_hat <= this level (0 = never)


@dataclass
class LexisReport:
    b_hat: float                       # math.inf when censored
    witness_p: object                  # true p of the witness (synthetic only); None if censored
    confirmations: list                # (level, true p, slots used) per confirmation
    audit_draws: list                  # per level
    audit_hits: list                   # per level
    certificates: list                 # eta_k upper bound on alpha-violating mass, per level
    slots_used: int
    registrations: int


def run_lexis(reservoirs, cfg, rng):
    K = len(reservoirs)
    weights = np.ones(K) if cfg.weights is None else np.asarray(cfg.weights, float)
    b_hat = math.inf
    witness_p = None
    current = [None] * K               # per level: [eprocess, p, a_j, slots]
    confirmations = []
    audit_n = [0] * K
    audit_s = [0] * K
    # Certificate budget per level is eps_audit / K, split evenly between the
    # exact zero-failure bound (reported when S_k = 0) and the betting CS
    # (reported otherwise); the reported bound is wrong only if one of them is.
    beta = cfg.eps_audit / K
    audit_cs = [BernoulliUpperCS(beta / 2) for _ in range(K)]
    slots = 0
    j = 0
    while slots < cfg.budget:
        active = [k for k in range(K) if k + 1 < b_hat]
        if not active:
            break
        w = weights[active] / weights[active].sum()
        k = active[rng.choice(len(active), p=w)]
        if rng.random() < cfg.audit_share:
            p = reservoirs[k](rng)
            z = int((rng.random(cfg.audit_repeats) < p).any())
            audit_n[k] += 1
            audit_s[k] += z
            audit_cs[k].update(z)
            slots += cfg.audit_repeats
            continue
        if current[k] is None:
            j += 1
            current[k] = [EProcess(cfg.alpha, cfg.strategy), reservoirs[k](rng),
                          polynomial_weight(j, cfg.eps), 0]
        ep, p, a, used = current[k]
        ep.update(int(rng.random() < p))
        current[k][3] = used + 1
        slots += 1
        if ep.crossed(a):
            confirmations.append((k + 1, p, used + 1))
            if k + 1 < b_hat:
                b_hat, witness_p = k + 1, p
            current[k] = None
            if cfg.stop_on_confirm or b_hat <= cfg.stop_at_level:
                break
        elif used + 1 >= cfg.cap:
            current[k] = None          # abandon (futility by cap)
    certs = []
    for k in range(K):
        q_up = zero_failure_upper(audit_n[k], beta / 2) if audit_s[k] == 0 else audit_cs[k].upper()
        certs.append(mass_bound(q_up, cfg.alpha, cfg.audit_repeats))
    return LexisReport(b_hat, witness_p, confirmations, audit_n, audit_s, certs, slots, j)
