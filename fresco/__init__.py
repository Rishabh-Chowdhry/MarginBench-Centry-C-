"""Reference implementation of the LEXIS statistical core used by FRESCO.

Stage 2 scope: an executable specification of the definitions and proofs in
docs/stage2_framework_and_algorithm.md. It is single-process and works on
synthetic oracles only; the distributed protocol arrives in Stage 3.
"""

from fresco.eprocess import EProcess, FixedBet, PlugInKelly
from fresco.spending import BudgetLedger, polynomial_weight
from fresco.certificates import BernoulliUpperCS, mass_bound, zero_failure_upper

__all__ = [
    "EProcess",
    "FixedBet",
    "PlugInKelly",
    "BudgetLedger",
    "polynomial_weight",
    "BernoulliUpperCS",
    "mass_bound",
    "zero_failure_upper",
]
