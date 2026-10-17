import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.ledger import CRASHED, DONE, Ledger, LedgerConfig, derive_key  # noqa: E402
from fresco.messages import Message  # noqa: E402

KEY = b"test-run-key"


def fresh(**kw):
    return Ledger(LedgerConfig(**kw), KEY)


def setup_candidate(led, level=2, content=7, worker="w0.1"):
    g = led.apply("grant", sender=worker, req_id=1, amount=0.01, now=0.0)
    r = led.apply("register", sender=worker, req_id=2, lease_id=g["lease_id"], content=content,
                  level=level, now=0.0)
    return g["lease_id"], r["j"]


def lease(led, j, count=1, worker="w0.1", now=0.0):
    return led.apply("lease_slots", sender=worker, j=j, count=count, now=now)["grants"]


def test_confirmation_lowers_frontier_and_prunes_higher_levels():
    led = fresh()
    lid, j_hi = setup_candidate(led, level=3, content=1)
    j_lo = led.apply("register", sender="w0.1", req_id=3, lease_id=lid, content=2, level=2, now=0)["j"]
    for g in lease(led, j_lo, count=20):
        led.apply("record", sender="w0.1", j=j_lo, k=g["k"], y=1, token=g["token"], now=1.0)
    assert led.b_hat == 2 and led.witness == j_lo
    assert led.candidates[j_hi]["status"] == "PRUNED"
    led.check_invariants()


def test_request_idempotency_no_double_spend():
    led = fresh()
    g = led.apply("grant", sender="w0.1", req_id=1, amount=0.01, now=0)
    r1 = led.apply("register", sender="w0.1", req_id=2, lease_id=g["lease_id"], content=5, level=1, now=0)
    r2 = led.apply("register", sender="w0.1", req_id=2, lease_id=g["lease_id"], content=5, level=1, now=0)
    assert r1 == r2 and len(led.candidates) == 1
    assert led.stats["duplicate_requests"] == 1
    assert math.isclose(led.leases[g["lease_id"]]["spent"], 0.01 / 2)


def test_write_once_and_token_fencing():
    led = fresh()
    _, j = setup_candidate(led)
    g = lease(led, j)[0]
    assert not led.apply("record", sender="w0.1", j=j, k=g["k"], y=1, token="bogus", now=1)["ok"]
    assert led.apply("record", sender="w0.1", j=j, k=g["k"], y=0, token=g["token"], now=1)["ok"]
    assert not led.apply("record", sender="w0.1", j=j, k=g["k"], y=1, token=g["token"], now=2)["ok"]
    assert led.slots[(j, g["k"])]["y"] == 0
    assert led.candidates[j]["ep"].trials == 1


def test_in_order_commit():
    led = fresh()
    _, j = setup_candidate(led)
    g1, g2 = lease(led, j, count=2)
    led.apply("record", sender="w0.1", j=j, k=g2["k"], y=1, token=g2["token"], now=1)
    assert led.candidates[j]["ep"].trials == 0          # slot 2 waits for slot 1
    led.apply("record", sender="w0.1", j=j, k=g1["k"], y=0, token=g1["token"], now=2)
    assert led.candidates[j]["ep"].trials == 2


def test_async_crash_is_zero_and_late_result_ignored():
    led = fresh(slot_ttl=10.0)
    _, j = setup_candidate(led)
    g = lease(led, j)[0]
    led.apply("tick", sender="ledger", now=11.0)
    assert led.slots[(j, g["k"])]["state"] == CRASHED
    assert led.candidates[j]["ep"].trials == 1 and led.candidates[j]["ep"].successes == 0
    assert not led.apply("record", sender="w0.1", j=j, k=g["k"], y=1, token=g["token"], now=12)["ok"]


def test_replay_mode_reuses_key_with_new_token():
    led = fresh(mode="replay", slot_ttl=10.0)
    _, j = setup_candidate(led)
    g = lease(led, j)[0]
    led.apply("tick", sender="ledger", now=11.0)
    g2 = lease(led, j, now=12.0)[0]
    assert g2["k"] == g["k"] and g2["key"] == g["key"] and g2["token"] != g["token"]
    assert led.candidates[j]["ep"].trials == 0


def test_unsafe_fresh_retry_changes_key():
    led = fresh(unsafe_fresh_retry=True, slot_ttl=10.0)
    _, j = setup_candidate(led)
    g = lease(led, j)[0]
    led.apply("tick", sender="ledger", now=11.0)
    g2 = lease(led, j, now=12.0)[0]
    assert g2["k"] == g["k"] and g2["key"] != g["key"]


def test_keys_are_prf_of_slot():
    led = fresh()
    _, j = setup_candidate(led)
    g = lease(led, j)[0]
    assert g["key"] == derive_key(KEY, "slot", j, g["k"])


def test_lease_fencing():
    led = fresh(budget_lease_ttl=100.0)
    g = led.apply("grant", sender="w0.1", amount=0.01, now=0)
    lid = g["lease_id"]
    assert led.apply("register", sender="w0.2", lease_id=lid, content=1, level=1, now=1)["reason"] == "UNKNOWN_LEASE"
    assert led.apply("register", sender="w0.1", lease_id=lid, content=1, level=1, now=101)["reason"] == "LEASE_CLOSED"
    g2 = led.apply("grant", sender="w0.1", amount=0.01, now=102)
    led.apply("close_lease", sender="w0.1", lease_id=g2["lease_id"], now=103)
    assert led.apply("register", sender="w0.1", lease_id=g2["lease_id"], content=2, level=1,
                     now=104)["reason"] == "LEASE_CLOSED"
    led.check_invariants()
    assert math.isclose(led.unleased, 0.05)   # both leases fully reclaimed


def test_content_dedup():
    led = fresh()
    lid, j = setup_candidate(led, content=9)
    r = led.apply("register", sender="w0.1", lease_id=lid, content=9, level=2, now=0)
    assert r["reason"] == "DUPLICATE_CONTENT" and r["j"] == j


def random_ops(led, rng, n=600):
    workers = ["w0.1", "w1.1", "w2.1"]
    leases, cands, grants = [], [], []
    now = 0.0
    for _ in range(n):
        now += float(rng.exponential(2.0))
        w = workers[rng.integers(3)]
        op = rng.integers(7)
        if op == 0:
            r = led.apply("grant", sender=w, amount=float(rng.uniform(0, 0.01)), now=now)
            if r["ok"]:
                leases.append((r["lease_id"], w))
        elif op == 1 and leases:
            lid, lw = leases[rng.integers(len(leases))]
            r = led.apply("register", sender=lw, lease_id=lid, content=int(rng.integers(50)),
                          level=int(rng.integers(1, 5)), now=now)
            if r["ok"]:
                cands.append(r["j"])
        elif op == 2 and cands:
            r = led.apply("lease_slots", sender=w, j=cands[rng.integers(len(cands))],
                          count=int(rng.integers(1, 4)), now=now)
            for g in r.get("grants", []):
                grants.append((r, g))
        elif op == 3 and grants:
            _, g = grants[rng.integers(len(grants))]
            j, k = (int(x) for x in g["token"].split(":")[:2])
            led.apply("record", sender=w, j=j, k=k, y=int(rng.random() < 0.6), token=g["token"], now=now)
        elif op == 4:
            led.apply("tick", sender="ledger", now=now)
        elif op == 5 and leases:
            lid, lw = leases[rng.integers(len(leases))]
            led.apply("close_lease", sender=lw, lease_id=lid, now=now)
        elif op == 6:
            r = led.apply("lease_audit", sender=w, level=int(rng.integers(1, 5)), now=now)
            if r["ok"] and rng.random() < 0.8:
                led.apply("record_audit", sender=w, level=r["level"], i=r["i"],
                          z=int(rng.random() < 0.2), token=r["token"], now=now + 1)
        led.check_invariants()


@pytest.mark.parametrize("mode", ["async", "replay"])
def test_random_operation_sequences_keep_invariants(mode):
    for seed in range(5):
        led = fresh(mode=mode, slot_ttl=15.0, cap=12)
        random_ops(led, np.random.default_rng(seed))


def test_journal_recovery_reproduces_state():
    led = fresh(slot_ttl=15.0, cap=12)
    random_ops(led, np.random.default_rng(42))
    rec = Ledger.recover(led.cfg, KEY, led.journal)
    assert rec.digest() == led.digest()
    assert rec.report() == led.report()


def test_audit_prefix_and_conservative_expiry():
    led = fresh(slot_ttl=10.0, audit_repeats=1)
    a1 = led.apply("lease_audit", sender="w0.1", level=1, now=0)
    a2 = led.apply("lease_audit", sender="w0.1", level=1, now=0)
    led.apply("record_audit", sender="w0.1", level=1, i=a2["i"], z=0, token=a2["token"], now=1)
    assert led.audit_commit[1] == 0                       # a1 still in flight
    led.apply("tick", sender="ledger", now=20)            # a1 expires -> z = 1
    assert led.audit_commit[1] == 2 and led.audit_hits[1] == 1


def test_message_roundtrip_and_validation():
    m = Message("record", "w0.1", "ledger", 3, {"j": 1, "k": 2, "y": 1, "token": "1:2:0", "trace_hash": "ab"})
    assert Message.from_json(m.to_json()) == m
    with pytest.raises(ValueError):
        Message("record", "w0.1", "ledger", 3, {"j": 1}).validate()
    with pytest.raises(ValueError):
        Message("nope", "a", "b", 1, {}).validate()
