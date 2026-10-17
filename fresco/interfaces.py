"""Extension points for real deployments (Stage 3 doc, section 6.2).

The simulator implements these with synthetic objects. A real MARGIN-Bench run
supplies: an Executor that runs one sandboxed agent episode from an immutable
snapshot with the given key, a Generator per surface, and optionally a
Scheduler. None of them can affect validity (Theorem 8) as long as they go
through the ledger protocol; they only affect efficiency.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence


@dataclass(frozen=True)
class SlotResult:
    y: int                       # committed violation per the authorization oracle (0/1)
    trace_hash: str              # content hash of the full episode trace in the object store
    oracle_version: str
    model_revision: str
    seeded: bool                 # True if execution is a deterministic function of the key


class Executor(Protocol):
    def execute(self, scenario_id: str, intervention: bytes, key: int, deadline_s: float) -> Optional[SlotResult]:
        """Run one episode from the scenario's immutable snapshot with randomness derived
        from `key`. Return None on crash/timeout; the ledger then imputes conservatively.
        Must reset all persistent state (memory, tool state) per call (assumption A1)."""


class Generator(Protocol):
    def propose(self, level: int, history: Sequence[dict]) -> bytes:
        """Adaptive candidate proposal. `history` holds only results the ledger released
        (committed outcomes); never keys of unregistered slots (assumption A2)."""

    def audit_draw(self, level: int, seed: int) -> bytes:
        """Non-adaptive draw from D_k, a pure function of the ledger-issued seed (I9)."""


class Scheduler(Protocol):
    def next_action(self, view: dict) -> dict:
        """Return {"kind": "audit"|"new"|"continue", ...}. Any policy is valid (Theorem 1)."""
