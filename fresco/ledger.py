"""FRESCO ledger: the linearizable state machine of Stage 2, sections 4.1-4.3.

The ledger is passive and deterministic. Every transition is a method that takes
the caller-supplied time `now`, so the same journal of operations always
reproduces the same state (write-ahead journal recovery, Stage 3 doc section 5.3).

Rules R1-R6 are implemented here:
  R1 slot keys u_{j,k} = PRF(run_key, j, k), revealed only by lease_slots
  R2 bets see only the committed prefix (fresco.eprocess)
  R3 write-once slots fenced by token; e-process consumes the in-order prefix
  R4 crashed slot -> Y = 0 (confirmation) / Z = 1 (audit); no fresh-key retry
  R5 every weight a_j is spent from a ledger lease bound to a worker incarnation
  R6 only the ledger confirms, by recomputing the e-process from stored slots

The `unsafe_*` switches remove single rules. They exist only to reproduce the
Theorem 9 counterexamples end-to-end and must never be used for real results.
"""

import hashlib
import hmac
import json
import math
from dataclasses import asdict, dataclass

from fresco.certificates import BernoulliUpperCS, mass_bound, zero_failure_upper
from fresco.eprocess import EProcess, PlugInKelly

ACTIVE, CONFIRMED, ABANDONED, PRUNED = "ACTIVE", "CONFIRMED", "ABANDONED", "PRUNED"
LEASED, DONE, CRASHED, FREE = "LEASED", "DONE", "CRASHED", "FREE"


@dataclass(frozen=True)
class LedgerConfig:
    alpha: float = 0.2
    eps: float = 0.05
    eps_audit: float = 0.05
    levels: int = 4
    cap: int = 60
    audit_repeats: int = 3
    audit_threshold: int = 1       # Z = 1{at least t of r audit runs violate} (Stage 3 section 2.4)
    audit_level: float = None      # certify mass of p >= audit_level (default alpha); a gap > alpha
                                   # makes the certificate informative when nulls sit just below alpha
    slot_ttl: float = 120.0
    budget_lease_ttl: float = 3600.0
    mode: str = "async"            # "async" (crash -> Y=0) or "replay" (re-run same key)
    bet_cap: float = 0.5
    dedup_content: bool = True
    max_slots: int = 10**9         # global oracle-call budget (audit runs included)
    unsafe_no_dedup: bool = False
    unsafe_fresh_retry: bool = False
    unsafe_arrival_order: bool = False
    unsafe_local_budget: bool = False

    def unsafe(self):
        return (self.unsafe_no_dedup or self.unsafe_fresh_retry
                or self.unsafe_arrival_order or self.unsafe_local_budget)


def derive_key(run_key, *parts):
    msg = "|".join(str(p) for p in parts).encode()
    return int.from_bytes(hmac.new(run_key, msg, hashlib.sha256).digest()[:8], "big")


class Ledger:
    def __init__(self, cfg, run_key, journal=True):
        if cfg.mode not in ("async", "replay"):
            raise ValueError("mode must be async or replay")
        self.cfg = cfg
        self.run_key = run_key
        self.journal = [] if journal else None
        self.candidates = {}     # j -> dict
        self.slots = {}          # (j, k) -> dict
        self.leases = {}         # lease_id -> dict
        self.audits = {}         # (level, i) -> dict
        self.audit_next = {k: 1 for k in range(1, cfg.levels + 1)}
        self.audit_commit = {k: 0 for k in range(1, cfg.levels + 1)}   # committed prefix length
        self.audit_hits = {k: 0 for k in range(1, cfg.levels + 1)}
        self.audit_cs = {k: BernoulliUpperCS(cfg.eps_audit / cfg.levels / 2)
                         for k in range(1, cfg.levels + 1)}
        self.unleased = cfg.eps
        self.local_unleased = {}  # worker -> budget (unsafe_local_budget only)
        self.b_hat = math.inf
        self.witness = None
        self.confirmations = []   # (j, level, n_slots, time)
        self.events = []          # frontier / status events for dissemination
        self.content_index = {}
        self.responses = {}       # (sender, req_id) -> response (idempotency)
        self.slots_leased = 0
        self.next_j = 1
        self.next_lease = 1
        self.stats = {"ignored_records": 0, "duplicate_requests": 0, "expired_slots": 0,
                      "pruned": 0, "abandoned": 0, "duplicates_applied": 0}

    # ------------------------------------------------------------------ dispatch
    def apply(self, op, sender=None, req_id=None, **kw):
        """Single entry point. Journaled before execution; idempotent per (sender, req_id)."""
        # unsafe_no_dedup also disables request-level idempotency for results, as a
        # naive at-least-once consumer would
        cache = req_id is not None and not (self.cfg.unsafe_no_dedup and op == "record")
        if cache and (sender, req_id) in self.responses:
            self.stats["duplicate_requests"] += 1
            return self.responses[(sender, req_id)]
        if self.journal is not None:
            self.journal.append({"op": op, "sender": sender, "req_id": req_id, "kw": kw})
        resp = getattr(self, "_op_" + op)(sender=sender, **kw)
        if cache:
            self.responses[(sender, req_id)] = resp
        return resp

    @classmethod
    def recover(cls, cfg, run_key, journal):
        """Rebuild state by replaying a journal (coordinator crash recovery)."""
        led = cls(cfg, run_key)
        for e in journal:
            led.apply(e["op"], sender=e["sender"], req_id=e["req_id"], **e["kw"])
        return led

    # ------------------------------------------------------------------ budget
    def _op_grant(self, sender, amount, now):
        if self.cfg.unsafe_local_budget:
            pool = self.local_unleased.setdefault(sender, self.cfg.eps)
        else:
            pool = self.unleased
        x = min(amount, pool)
        if x <= 1e-15:
            return {"ok": False, "reason": "NO_BUDGET"}
        if self.cfg.unsafe_local_budget:
            self.local_unleased[sender] = pool - x
        else:
            self.unleased -= x
        lid = self.next_lease
        self.next_lease += 1
        self.leases[lid] = {"worker": sender, "amount": x, "spent": 0.0, "n": 0, "open": True,
                            "expires": now + self.cfg.budget_lease_ttl}
        return {"ok": True, "lease_id": lid, "amount": x, "expires": now + self.cfg.budget_lease_ttl}

    def _op_close_lease(self, sender, lease_id, now):
        lease = self.leases.get(lease_id)
        if lease is None or lease["worker"] != sender:
            return {"ok": False, "reason": "UNKNOWN_LEASE"}
        self._close(lease_id)
        return {"ok": True}

    def _close(self, lid):
        lease = self.leases[lid]
        if lease["open"]:
            lease["open"] = False
            back = lease["amount"] - lease["spent"]
            if self.cfg.unsafe_local_budget:
                self.local_unleased[lease["worker"]] += back
            else:
                self.unleased += back

    # ------------------------------------------------------------------ candidates
    def _op_register(self, sender, lease_id, content, level, now):
        lease = self.leases.get(lease_id)
        if lease is None or lease["worker"] != sender:
            return {"ok": False, "reason": "UNKNOWN_LEASE"}
        if not lease["open"] or now > lease["expires"]:
            if lease["open"]:
                self._close(lease_id)
            return {"ok": False, "reason": "LEASE_CLOSED"}
        if not 1 <= level <= self.cfg.levels:
            return {"ok": False, "reason": "BAD_LEVEL"}
        if level >= self.b_hat:
            return {"ok": False, "reason": "PRUNED"}
        key = (level, content)
        if self.cfg.dedup_content and key in self.content_index:
            return {"ok": False, "reason": "DUPLICATE_CONTENT", "j": self.content_index[key]}
        i = lease["n"] + 1
        a = lease["amount"] / (i * (i + 1))
        lease["n"] = i
        lease["spent"] += a
        j = self.next_j
        self.next_j += 1
        self.candidates[j] = {
            "level": level, "content": content, "a": a, "lease": lease_id, "owner": sender,
            "status": ACTIVE, "next_new": 1, "free": [], "ep": EProcess(self.cfg.alpha, PlugInKelly(self.cfg.bet_cap)),
        }
        self.content_index[key] = j
        return {"ok": True, "j": j, "a": a}

    def _op_abandon(self, sender, j, now):
        c = self.candidates.get(j)
        if c is not None and c["status"] == ACTIVE:
            c["status"] = ABANDONED
            self.stats["abandoned"] += 1
            self.events.append(("status", j, ABANDONED, now))
        return {"ok": True}

    # ------------------------------------------------------------------ slots
    def _op_lease_slots(self, sender, j, count, now):
        c = self.candidates.get(j)
        if c is None:
            return {"ok": False, "reason": "UNKNOWN"}
        if c["status"] != ACTIVE:
            return {"ok": False, "reason": c["status"]}
        if c["level"] >= self.b_hat:
            self._prune(c, j, now)
            return {"ok": False, "reason": PRUNED}
        grants = []
        while len(grants) < count:
            if self.slots_leased >= self.cfg.max_slots:
                break
            if c["free"]:
                c["free"].sort()
                k = c["free"].pop(0)
                slot = self.slots[(j, k)]
                slot["attempt"] += 1
            elif c["next_new"] <= self.cfg.cap:
                k = c["next_new"]
                c["next_new"] += 1
                slot = {"state": FREE, "attempt": 0, "y": None}
                self.slots[(j, k)] = slot
            else:
                break
            if self.cfg.unsafe_fresh_retry:
                key = derive_key(self.run_key, "slot", j, k, slot["attempt"])
            else:
                key = derive_key(self.run_key, "slot", j, k)   # same key on replay
            token = f"{j}:{k}:{slot['attempt']}"
            slot.update(state=LEASED, token=token, worker=sender, t0=now)
            self.slots_leased += 1
            grants.append({"k": k, "key": key, "token": token})
        if not grants:
            return {"ok": False, "reason": "BUDGET" if self.slots_leased >= self.cfg.max_slots else "CAP"}
        return {"ok": True, "grants": grants}

    def _op_record(self, sender, j, k, y, token, now, trace_hash=None):
        slot = self.slots.get((j, k))
        c = self.candidates.get(j)
        if slot is None or c is None or y not in (0, 1):
            self.stats["ignored_records"] += 1
            return {"ok": False, "reason": "UNKNOWN"}
        if slot["state"] == LEASED and slot["token"] == token:
            slot.update(state=DONE, y=y, trace_hash=trace_hash)
            if self.cfg.unsafe_arrival_order:
                self._consume_now(c, j, y, now)
            else:
                self._advance(c, j, now)
            return {"ok": True}
        if (self.cfg.unsafe_no_dedup and slot["state"] == DONE and slot.get("token") == token
                and c["status"] == ACTIVE):
            self._apply_extra(c, j, y, now)          # naive accumulator counts it again
            self.stats["duplicates_applied"] += 1
            return {"ok": True, "duplicate_applied": True}
        self.stats["ignored_records"] += 1
        return {"ok": False, "reason": "STALE_OR_DUPLICATE"}

    def _consume_now(self, c, j, y, now):
        if c["status"] != ACTIVE:
            return
        c["ep"].update(y)
        self._check(c, j, now)

    def _apply_extra(self, c, j, y, now):
        # unsafe_no_dedup only: multiply in one more factor for an already-counted
        # slot without moving the slot index (models a duplicate-applying consumer)
        ep = c["ep"]
        lam = ep.strategy(ep.successes, ep.trials, ep.alpha)
        ep.log_e += math.log1p(lam * (y - ep.alpha))
        ep.max_log_e = max(ep.max_log_e, ep.log_e)
        self._check(c, j, now)

    def _advance(self, c, j, now):
        while c["status"] == ACTIVE:
            slot = self.slots.get((j, c["ep"].trials + 1))
            if slot is None or slot["state"] not in (DONE, CRASHED):
                break
            y = slot["y"] if slot["state"] == DONE else 0      # R4
            c["ep"].update(y)
            self._check(c, j, now)

    def _check(self, c, j, now):
        if c["ep"].crossed(c["a"]):
            c["status"] = CONFIRMED
            self.confirmations.append((j, c["level"], c["ep"].trials, now))
            self.events.append(("status", j, CONFIRMED, now))
            if c["level"] < self.b_hat:
                self.b_hat = c["level"]
                self.witness = j
                self.events.append(("frontier", self.b_hat, j, now))
                for jj, cc in self.candidates.items():
                    if cc["status"] == ACTIVE and cc["level"] >= self.b_hat:
                        self._prune(cc, jj, now)
        elif c["ep"].trials >= self.cfg.cap:
            c["status"] = ABANDONED
            self.stats["abandoned"] += 1
            self.events.append(("status", j, ABANDONED, now))

    def _prune(self, c, j, now):
        if c["status"] == ACTIVE:
            c["status"] = PRUNED
            self.stats["pruned"] += 1
            self.events.append(("status", j, PRUNED, now))

    # ------------------------------------------------------------------ audits
    def _op_lease_audit(self, sender, level, now):
        if not 1 <= level <= self.cfg.levels or level >= self.b_hat:
            return {"ok": False, "reason": "PRUNED"}
        if self.slots_leased + self.cfg.audit_repeats > self.cfg.max_slots:
            return {"ok": False, "reason": "BUDGET"}
        i = self.audit_next[level]
        self.audit_next[level] += 1
        seed = derive_key(self.run_key, "audit-content", level, i)    # non-adaptive draw (I9)
        keys = [derive_key(self.run_key, "audit", level, i, r) for r in range(self.cfg.audit_repeats)]
        token = f"A{level}:{i}"
        self.audits[(level, i)] = {"state": LEASED, "token": token, "t0": now, "z": None}
        self.slots_leased += self.cfg.audit_repeats
        return {"ok": True, "level": level, "i": i, "seed": seed, "keys": keys, "token": token}

    def _op_record_audit(self, sender, level, i, z, token, now):
        a = self.audits.get((level, i))
        if a is None or a["state"] != LEASED or a["token"] != token or z not in (0, 1):
            self.stats["ignored_records"] += 1
            return {"ok": False, "reason": "STALE_OR_DUPLICATE"}
        a.update(state=DONE, z=z)
        self._advance_audit(level)
        return {"ok": True}

    def _advance_audit(self, level):
        # R3 for audits: count only the in-order prefix, so latency cannot select outcomes
        while True:
            a = self.audits.get((level, self.audit_commit[level] + 1))
            if a is None or a["state"] not in (DONE, CRASHED):
                return
            z = a["z"] if a["state"] == DONE else 1             # R4: crash counts against robustness
            self.audit_commit[level] += 1
            self.audit_hits[level] += z
            self.audit_cs[level].update(z)

    # ------------------------------------------------------------------ time
    def _op_tick(self, sender, now):
        """Expire slot leases, audit leases and budget leases whose deadline passed."""
        expired = [(jk, s) for jk, s in self.slots.items()
                   if s["state"] == LEASED and now > s["t0"] + self.cfg.slot_ttl]
        for (j, k), s in expired:
            self.stats["expired_slots"] += 1
            c = self.candidates[j]
            if self.cfg.mode == "replay" or self.cfg.unsafe_fresh_retry:
                s.update(state=FREE, token=None)
                if c["status"] == ACTIVE:
                    c["free"].append(k)
            else:
                s.update(state=CRASHED, token=None)
                if self.cfg.unsafe_arrival_order:
                    self._consume_now(c, j, 0, now)
                else:
                    self._advance(c, j, now)
        for (level, i), a in self.audits.items():
            if a["state"] == LEASED and now > a["t0"] + self.cfg.slot_ttl * self.cfg.audit_repeats:
                a.update(state=CRASHED, token=None)
                self._advance_audit(level)
        for lid, lease in self.leases.items():
            if lease["open"] and now > lease["expires"]:
                self._close(lid)
        return {"ok": True, "expired": len(expired)}

    # ------------------------------------------------------------------ reporting
    def certificates(self):
        beta = self.cfg.eps_audit / self.cfg.levels
        out = {}
        for k in range(1, self.cfg.levels + 1):
            n = self.audit_commit[k]
            q = zero_failure_upper(n, beta / 2) if self.audit_hits[k] == 0 else self.audit_cs[k].upper()
            out[k] = {"n": n, "hits": self.audit_hits[k],
                      "eta": mass_bound(q, self.cfg.audit_level or self.cfg.alpha,
                                        self.cfg.audit_repeats, self.cfg.audit_threshold),
                      "level": self.cfg.audit_level or self.cfg.alpha}
        return out

    def report(self):
        return {"b_hat": None if self.b_hat == math.inf else self.b_hat,
                "witness": self.witness,
                "confirmations": [list(c) for c in self.confirmations],
                "certificates": self.certificates(),
                "registrations": self.next_j - 1,
                "slots_leased": self.slots_leased,
                "stats": dict(self.stats),
                "unsafe": self.cfg.unsafe()}

    def digest(self):
        """Hash of the observable state; equal digests <=> equal ledgers (for recovery tests)."""
        state = {
            "cand": {j: [c["level"], c["content"], c["a"], c["status"], c["ep"].trials,
                         c["ep"].successes, round(c["ep"].log_e, 12)] for j, c in self.candidates.items()},
            "slots": {f"{j},{k}": [s["state"], s.get("y"), s["attempt"]] for (j, k), s in self.slots.items()},
            "leases": {lid: [l["amount"], l["spent"], l["open"]] for lid, l in self.leases.items()},
            "audits": {f"{l},{i}": [a["state"], a["z"]] for (l, i), a in self.audits.items()},
            "b_hat": str(self.b_hat), "unleased": self.unleased,
        }
        return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()

    def check_invariants(self):
        """I1-I7 (Stage 2 section 4.3). Raises AssertionError on violation."""
        if not self.cfg.unsafe_local_budget:
            committed = sum(l["amount"] if l["open"] else l["spent"] for l in self.leases.values())
            assert committed + self.unleased <= self.cfg.eps + 1e-12, "I1"
            assert sum(c["a"] for c in self.candidates.values()) <= self.cfg.eps + 1e-12, "I1"
        for lid, l in self.leases.items():
            assert l["spent"] <= l["amount"] + 1e-12, f"I2 lease {lid}"
        for j, c in self.candidates.items():
            n = c["ep"].trials
            if not self.cfg.unsafe_arrival_order and not self.cfg.unsafe_no_dedup:
                for k in range(1, n + 1):
                    assert self.slots[(j, k)]["state"] in (DONE, CRASHED), f"I4 cand {j} slot {k}"
            if c["status"] == CONFIRMED:
                assert c["ep"].crossed(c["a"]), f"I6 cand {j}"
        confirmed = [c["level"] for c in self.candidates.values() if c["status"] == CONFIRMED]
        assert (min(confirmed) if confirmed else math.inf) == self.b_hat, "I7"


def config_dict(cfg):
    return asdict(cfg)
