"""Error-budget spending.

The global invariant (I1/I2 in the Stage 2 doc) is sum_j a_j <= eps over every
candidate ever registered by any worker. BudgetLedger is the single-process
model of the linearizable ledger that enforces it: leases are carved from the
global budget, candidates spend from a lease, and closing a lease returns only
its unspent part. Stage 3 replaces this with a durable, replicated ledger.
"""


def polynomial_weight(j, eps):
    """a_j = eps / (j (j + 1)) for the j-th registration (j >= 1); sum_j a_j = eps.
    Threshold log(1/a_j) grows like 2 log j, not linearly as geometric spending would."""
    if j < 1:
        raise ValueError("registration index starts at 1")
    return eps / (j * (j + 1))


class BudgetError(RuntimeError):
    pass


class BudgetLedger:
    def __init__(self, eps):
        self.eps = eps
        self.unleased = eps
        self.leases = {}     # lease_id -> dict(amount, spent, open)
        self.weights = {}    # candidate_id -> (lease_id, a_j)
        self._next_lease = 0

    def grant(self, amount):
        if amount <= 0 or amount > self.unleased + 1e-15:
            raise BudgetError("insufficient unleased budget")
        self.unleased -= amount
        lease_id = self._next_lease
        self._next_lease += 1
        self.leases[lease_id] = {"amount": amount, "spent": 0.0, "open": True, "n": 0}
        return lease_id

    def register(self, lease_id, candidate_id, fraction=None):
        """Spend from an open lease. Default rule: polynomial spending within the
        lease, a = amount / (n (n + 1)) for the lease's n-th registration."""
        lease = self.leases[lease_id]
        if not lease["open"]:
            raise BudgetError("lease closed (fenced)")
        if candidate_id in self.weights:
            raise BudgetError("candidate already registered")
        n = lease["n"] + 1
        a = polynomial_weight(n, lease["amount"]) if fraction is None else fraction * lease["amount"]
        if lease["spent"] + a > lease["amount"] + 1e-15:
            raise BudgetError("lease exhausted")
        lease["spent"] += a
        lease["n"] = n
        self.weights[candidate_id] = (lease_id, a)
        return a

    def close(self, lease_id):
        """Fence the lease and reclaim its unspent budget."""
        lease = self.leases[lease_id]
        if lease["open"]:
            lease["open"] = False
            self.unleased += lease["amount"] - lease["spent"]

    def total_committed(self):
        """Budget that can no longer be re-granted: spent by candidates, or held by open leases."""
        return sum(l["spent"] if not l["open"] else l["amount"] for l in self.leases.values())

    def check_invariant(self):
        spent = sum(a for _, a in self.weights.values())
        assert spent <= self.eps + 1e-12, "I1 violated"
        assert self.total_committed() + self.unleased <= self.eps + 1e-12, "I1 violated"
        for lid, lease in self.leases.items():
            assert lease["spent"] <= lease["amount"] + 1e-12, f"I2 violated on lease {lid}"
