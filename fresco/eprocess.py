"""Betting e-process for one candidate's null H0: p <= alpha.

E_n = prod_{i<=n} (1 + lambda_i (Y_i - alpha)),  lambda_i in [0, 1/alpha).

Under H0 every factor has conditional mean 1 + lambda_i (p - alpha) <= 1 and is
strictly positive, so E_n is a non-negative supermartingale and Ville's
inequality gives P(sup_n E_n >= 1/a) <= a.

Predictability is enforced structurally: a strategy only ever sees the
(successes, trials) count of the committed prefix Y_1..Y_{i-1}. It cannot see
the outcome it is betting on or any out-of-order result (rule R2, Stage 2 doc).
"""

import math


class FixedBet:
    """Constant betting fraction. lam = (p1 - alpha) / (alpha (1 - alpha)) is
    Kelly-optimal against the alternative p1 and has log-growth KL(p1 || alpha)."""

    def __init__(self, lam):
        self.lam = float(lam)

    @classmethod
    def kelly(cls, alpha, p1):
        if not alpha < p1 < 1:
            raise ValueError("need alpha < p1 < 1")
        return cls((p1 - alpha) / (alpha * (1 - alpha)))

    def __call__(self, successes, trials, alpha):
        return self.lam


class PlugInKelly:
    """Predictable plug-in Kelly bet: smoothed prefix mean, clipped to
    [0, cap/alpha]. Consistent: rejects any fixed p > alpha eventually a.s."""

    def __init__(self, cap=0.5, prior=0.5):
        if not 0 < cap < 1:
            raise ValueError("cap must be in (0, 1)")
        self.cap = cap
        self.prior = prior

    def __call__(self, successes, trials, alpha):
        p_hat = (successes + self.prior) / (trials + 2 * self.prior)
        lam = (p_hat - alpha) / (alpha * (1 - alpha))
        return min(max(lam, 0.0), self.cap / alpha)


class EProcess:
    def __init__(self, alpha, strategy):
        if not 0 < alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        self.alpha = alpha
        self.strategy = strategy
        self.trials = 0
        self.successes = 0
        self.log_e = 0.0
        self.max_log_e = 0.0

    def update(self, y):
        """Consume the next committed slot outcome y in {0, 1}."""
        if y not in (0, 1):
            raise ValueError("outcome must be 0 or 1")
        lam = self.strategy(self.successes, self.trials, self.alpha)
        if not 0 <= lam < 1 / self.alpha:
            raise ValueError(f"bet {lam} outside [0, 1/alpha)")
        self.log_e += math.log1p(lam * (y - self.alpha))
        self.trials += 1
        self.successes += y
        self.max_log_e = max(self.max_log_e, self.log_e)
        return self.log_e

    def crossed(self, a):
        """True once sup_n E_n >= 1/a, i.e. the candidate is confirmed at level a."""
        return self.max_log_e >= math.log(1.0 / a)


def log_growth(lam, alpha, p):
    """Expected log-increment g(lam, p) of one factor when Y ~ Bernoulli(p)."""
    return p * math.log1p(lam * (1 - alpha)) + (1 - p) * math.log1p(-lam * alpha)


def kl_bernoulli(p, q):
    """KL(Bernoulli(p) || Bernoulli(q))."""
    out = 0.0
    if p > 0:
        out += p * math.log(p / q)
    if p < 1:
        out += (1 - p) * math.log((1 - p) / (1 - q))
    return out


def wald_expected_stopping_bound(a, lam, alpha, p):
    """Upper bound on E[tau] for crossing log(1/a) with fixed bet lam when
    Y ~ Bernoulli(p) and g(lam, p) > 0 (Proposition 4, Stage 2 doc)."""
    g = log_growth(lam, alpha, p)
    if g <= 0:
        return math.inf
    return (math.log(1.0 / a) + math.log1p(lam * (1 - alpha))) / g
