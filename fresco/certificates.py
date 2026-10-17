"""Cost-level non-discovery certificates (Proposition 2, Stage 2 doc).

Audit draws at level k are delta ~ D_k (non-adaptive), each run r times. Z = 1 if
any run violates (crashes count as Z = 1, which is conservative here). Z ~
Bernoulli(q_k) with q_k >= mu_k (1 - (1 - alpha)^r), where mu_k is the D_k-mass
of alpha-violating interventions. An anytime-valid upper bound on q_k therefore
bounds mu_k.
"""

import math

import numpy as np


def zero_failure_upper(n, beta):
    """Anytime-valid upper bound on q after n draws with zero successes:
    P(exists n: S_n = 0 and q > 1 - beta^(1/n)) <= beta."""
    if n <= 0:
        return 1.0
    return 1.0 - beta ** (1.0 / n)


def binom_tail(r, p, t):
    """P(Binomial(r, p) >= t)."""
    return sum(math.comb(r, i) * p ** i * (1 - p) ** (r - i) for i in range(t, r + 1))


def mass_bound(q_upper, alpha, r, t=1):
    """Bound on mu = D{delta: p(delta) >= alpha} from an upper bound on q = P(Z = 1),
    where Z = 1{at least t of r runs violate}. Because the binomial tail is
    increasing in p, every draw with p >= alpha has P(Z = 1) >= P(Bin(r, alpha) >= t),
    so q >= mu * binom_tail(r, alpha, t). t = 1 recovers 1 - (1 - alpha)^r."""
    return min(1.0, q_upper / binom_tail(r, alpha, t))


class BernoulliUpperCS:
    """Anytime-valid upper confidence sequence for a Bernoulli mean q.

    For each grid value g, H_g: q >= g is tested with the betting e-process
    prod (1 + lam_i (g - Z_i)), lam_i in [0, 1/(1-g)), lam_i predictable.
    U_n = min{g : every grid value >= g is rejected by time n}.
    If q > U_n then the largest grid value g <= q is rejected although H_g is
    true, which has probability <= beta by Ville. No union bound over the grid
    is needed.
    """

    def __init__(self, beta, grid_size=400, cap=0.5):
        self.beta = beta
        self.grid = np.linspace(0.0, 1.0, grid_size + 1)[1:-1]  # exclude 0 and 1
        self.log_e = np.zeros_like(self.grid)
        self.rejected = np.zeros(self.grid.shape, dtype=bool)
        self.cap = cap
        self.n = 0
        self.s = 0
        self._threshold = math.log(1.0 / beta)

    def update(self, z):
        g = self.grid
        z_hat = (self.s + 0.5) / (self.n + 1.0)
        lam = np.clip((g - z_hat) / (g * (1 - g)), 0.0, self.cap / (1 - g))
        self.log_e += np.log1p(lam * (g - z))
        self.rejected |= self.log_e >= self._threshold
        self.n += 1
        self.s += z

    def upper(self):
        # smallest g such that all grid values >= g are rejected
        not_rej = np.nonzero(~self.rejected)[0]
        if len(not_rej) == 0:
            return float(self.grid[0])
        last = not_rej[-1]
        return float(self.grid[last + 1]) if last + 1 < len(self.grid) else 1.0
