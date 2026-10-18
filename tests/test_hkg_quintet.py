import copy
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.hkg.corrupt import coordinated_tamper, corrupt_fabric, tamper_node  # noqa: E402
from fresco.hkg.graph import DOMAINS, DomainStore, Fabric, Node, witnesses  # noqa: E402
from fresco.hkg.repair import (QUARANTINED, RECONSTRUCTED, REPAIRED, VERIFIED, RunParams, TWGRConfig,  # noqa: E402
                               discover, report, twgr)
from fresco.quintet.cluster import Quintet, QuintetConfig  # noqa: E402
from fresco.sim.scenario import Level, Scenario  # noqa: E402

P = RunParams(eps=0.05, lease_size=8, run_key=b"test-key", alpha=0.2, cap=60)


@pytest.fixture(scope="module")
def run():
    q = Quintet(Scenario(), P, QuintetConfig(workers=3, budget=1200, crash=0.05), np.random.default_rng(3))
    q.run()
    return q


def fresh(run):
    return copy.deepcopy(run.fabric)


def test_node_roundtrip_and_write_once():
    n = Node("Result", "1:1", {"y": 1}, "recorder", (("for", "Candidate", "1", "ab" * 16),))
    assert Node.decode(n.encode()) == n
    st = DomainStore("recorder")
    assert st.put(n.id, n.encode()) and not st.put(n.id, b"other")
    with pytest.raises(ValueError):
        Node.decode(b"{not json")


def test_witness_placement_distinct():
    for k in range(50):
        w = witnesses(("Result", str(k)), "recorder")
        assert len(set(w)) == 2 and "recorder" not in w and set(w) <= set(DOMAINS)


def test_clean_graph_all_verified(run):
    fab = fresh(run)
    status, acc = twgr(fab, P)
    assert set(status.values()) == {VERIFIED}
    assert report(acc) == run.truth_report()


def test_single_copy_corruption_is_repaired_and_healed(run):
    fab = fresh(run)
    nid = next(i for i in fab.truth if i[0] == "Result")
    owner = "recorder"
    fab.stores[owner].blobs[nid] = tamper_node(Node.decode(fab.stores[owner].blobs[nid])).encode()
    status, acc = twgr(fab, P)
    assert status[nid] == REPAIRED and acc[nid].encode() == fab.truth[nid]
    assert fab.stores[owner].blobs[nid] == fab.truth[nid]       # healed in place


def test_derivable_record_reconstructed_after_total_loss(run):
    fab = fresh(run)
    nid = next(i for i in fab.truth if i[0] == "Key")
    for st in fab.stores.values():
        st.blobs.pop(nid, None)
    status, acc = twgr(fab, P)
    assert status[nid] == RECONSTRUCTED and acc[nid].encode() == fab.truth[nid]


def test_non_derivable_total_loss_is_quarantined(run):
    fab = fresh(run)
    nid = next(i for i in fab.truth if i[0] == "Result")
    for st in fab.stores.values():
        st.blobs.pop(nid, None)
    status, _ = twgr(fab, P)
    assert status[nid] == QUARANTINED


def test_minority_adversary_cannot_fabricate(run):
    fab = fresh(run)
    nid = next(i for i in fab.truth if i[0] == "Result" and Node.decode(fab.truth[i]).payload.get("y") == 0)
    place = fab.placement(Node.decode(fab.truth[nid]))
    coordinated_tamper(fab, nid, place[:2])                     # 2 of 3 copies, consistently
    status, acc = twgr(fab, P)
    assert nid not in acc or acc[nid].encode() == fab.truth[nid]


def test_replica_majority_baseline_is_fooled(run):
    fab = fresh(run)
    nid = next(i for i in fab.truth if i[0] == "Result" and Node.decode(fab.truth[i]).payload.get("y") == 0)
    place = fab.placement(Node.decode(fab.truth[nid]))
    coordinated_tamper(fab, nid, place[:2])
    cfg = TWGRConfig(copy_votes=True, use_log_anchors=False, use_edge_anchors=False, use_derivation=False)
    _, acc = twgr(fab, P, cfg)
    assert acc[nid].payload["y"] == 1                          # wrong value accepted


def test_best_effort_accepts_tampered_owner_copy(run):
    fab = fresh(run)
    nid = next(i for i in fab.truth if i[0] == "Result" and Node.decode(fab.truth[i]).payload.get("y") == 0)
    fab.stores["recorder"].blobs[nid] = tamper_node(Node.decode(fab.stores["recorder"].blobs[nid])).encode()
    _, acc = twgr(fab, P, TWGRConfig(quarantine=False))
    assert acc[nid].payload["y"] == 1


@pytest.mark.parametrize("rho", [0.1, 0.3, 0.6])
def test_repair_never_adds_confirmations_or_wrong_records(run, rho):
    fab = fresh(run)
    corrupt_fabric(fab, rho, np.random.default_rng(int(rho * 100)))
    status, acc = twgr(fab, P)
    truth_conf = {k for _, k in run.truth_report()["confirmed"]}
    assert {k for _, k in report(acc)["confirmed"]} <= truth_conf
    for nid, node in acc.items():
        if nid[0] != "Confirmation":
            assert node.encode() == fab.truth[nid], nid


def test_phantom_ids_not_discovered(run):
    fab = fresh(run)
    fab.stores["archivist"].append_anchor(("Result", "999:1"), "ff" * 16)
    assert ("Result", "999:1") not in discover(fab)


def test_store_persistence_skips_corrupted_lines(tmp_path, run):
    st = copy.deepcopy(run.fabric.stores["recorder"])
    path = tmp_path / "recorder.jsonl"
    st.save(path)
    raw = path.read_bytes().split(b"\n")
    raw[0] = raw[0][:10]
    path.write_bytes(b"\n".join(raw))
    loaded = DomainStore.load("recorder", path)
    assert len(loaded.blobs) == len(st.blobs) - 1 and loaded.log == st.log


def test_quintet_single_writer_per_type(run):
    owners = {}
    for b in run.fabric.truth.values():
        n = Node.decode(b)
        owners.setdefault(n.type, set()).add(n.owner)
    assert all(len(v) == 1 for v in owners.values())
    assert set().union(*owners.values()) <= set(DOMAINS) - {"archivist"}


def test_derivation_verified_record_is_stable(run):
    """A record whose anchors are all lost but whose copies equal its exact derivation is
    VERIFIED (by derivation), so repeated scans converge to no further repairs."""
    fab = fresh(run)
    nid = next(i for i in fab.truth if i[0] == "Key")
    for st in fab.stores.values():
        st.log = [ln for ln in st.log if f'"{nid[0]}:{nid[1]}"' not in ln]
        for oid in list(st.blobs):
            if oid[0] == "Result" and oid[1] == nid[1]:
                del st.blobs[oid]
    twgr(fab, P)
    status, _ = twgr(fab, P)
    assert status[nid] == VERIFIED


# ---------------------------------------------------------------- TWGR-S (signed evidence)
S = TWGRConfig(authenticate=True)


def _all_domains_rewrite(fab, nid, bad):
    from experiments.e11_adversary import control
    control(fab, nid, bad, list(DOMAINS))


def test_twgr_s_clean_graph_all_verified(run):
    status, acc = twgr(fresh(run), run.p, S)
    assert set(status.values()) == {VERIFIED}
    assert report(acc) == run.truth_report()


@pytest.mark.parametrize("pick", ["Result", "Confirmation", "Candidate", "Lease"])
def test_twgr_s_even_all_five_domains_cannot_fabricate(run, pick):
    """The loophole of plain TWGR: an adversary holding a majority (here all five) of the
    domains could make a forged value win the vote. Under TWGR-S forged evidence is never
    admissible and derivable records are always recomputed."""
    fab = fresh(run)

    def ok(i):
        p = Node.decode(fab.truth[i]).payload
        return {"Result": p.get("y") == 0, "Confirmation": not p.get("confirmed", True),
                "Candidate": p.get("level", 1) > 1, "Lease": True}[pick]
    nid = next(i for i in sorted(fab.truth) if i[0] == pick and ok(i))
    _all_domains_rewrite(fab, nid, tamper_node(Node.decode(fab.truth[nid])))
    _, plain = twgr(copy.deepcopy(fab), run.p)
    status, acc = twgr(fab, run.p, S)
    assert nid not in acc or acc[nid].encode() == fab.truth[nid]
    truth_conf = {k for _, k in run.truth_report()["confirmed"]}
    assert {k for _, k in report(acc)["confirmed"]} <= truth_conf
    if pick == "Confirmation":                             # plain TWGR is fooled: it adds a confirmation
        assert {k for _, k in report(plain)["confirmed"]} - truth_conf


def test_twgr_s_suppression_is_only_conservative(run):
    fab = fresh(run)
    nid = next(i for i in sorted(fab.truth) if i[0] == "Result" and Node.decode(fab.truth[i]).payload.get("y") == 1)
    n = Node.decode(fab.truth[nid])
    _all_domains_rewrite(fab, nid, Node(n.type, n.key, {"crashed": True}, n.owner, n.edges))
    _, acc = twgr(fab, run.p, S)
    assert acc[nid].payload == {"crashed": True}
    assert {k for _, k in report(acc)["confirmed"]} <= {k for _, k in run.truth_report()["confirmed"]}


def test_twgr_s_rejects_unknown_device_and_equivocation(run):
    from fresco.hkg import sign as sg
    fab = fresh(run)
    nid = next(i for i in sorted(fab.truth) if i[0] == "Result" and Node.decode(fab.truth[i]).payload.get("y") == 0)
    n = Node.decode(fab.truth[nid])
    j, k = nid[1].rsplit(":", 1)
    cand = Node.decode(fab.truth[("Candidate", j)])
    from fresco.hkg.repair import prf_key
    rogue = sg.device_key("attacker")
    sig = sg.sign_result(rogue, run.p.manifest["run_id"], j, int(k), 1, sg.request_hash(cand.payload),
                         prf_key(run.p.run_key, j, int(k)))
    _all_domains_rewrite(fab, nid, Node(n.type, n.key, {**n.payload, "y": 1, "sig": sig}, n.owner, n.edges))
    status, acc = twgr(fab, run.p, S)
    assert nid not in acc and status[nid] == QUARANTINED
    # a genuine device signing two different outcomes for one slot is quarantined too
    fab = fresh(run)
    w = cand.payload["worker"]
    sk = sg.device_key(f"device-secret|0|{w}")
    sig2 = sg.sign_result(sk, run.p.manifest["run_id"], j, int(k), 1, sg.request_hash(cand.payload),
                          prf_key(run.p.run_key, j, int(k)))
    fab.stores["recorder"].blobs[nid] = Node(n.type, n.key, {**n.payload, "y": 1, "sig": sig2}, n.owner, n.edges).encode()
    status, acc = twgr(fab, run.p, S)
    assert status[nid] == QUARANTINED


def test_robust_confirmation_requires_every_unsigned_assignment():
    from fresco.hkg.repair import MAX_UNSIGNED, robust_confirmed
    alloc = Node("Allocation", "1", {"a": 0.003}, "treasurer")
    signed = lambda y: Node("Result", "1:x", {"y": y, "sig": "s"}, "recorder")  # noqa: E731
    crash = Node("Result", "1:x", {"crashed": True}, "recorder")
    strong = [signed(1)] * 25
    assert robust_confirmed(alloc, strong + [crash], P)
    assert not robust_confirmed(alloc, [crash] * 25, P)                         # zeros could hide anything
    assert not robust_confirmed(alloc, strong + [crash] * (MAX_UNSIGNED + 1), P)


def test_twgr_s_random_corruption_is_safe(run):
    for rho in (0.1, 0.4):
        fab = fresh(run)
        corrupt_fabric(fab, rho, np.random.default_rng(int(rho * 1000)))
        _, acc = twgr(fab, run.p, S)
        assert {k for _, k in report(acc)["confirmed"]} <= {k for _, k in run.truth_report()["confirmed"]}
        for nid, node in acc.items():                      # signed content genuine; edges to accepted
            if nid[0] == "Confirmation":                    # records exact (an edge to an unrecoverable
                continue                                    # record cannot be checked by anyone)
            true = Node.decode(fab.truth[nid])
            assert node.payload == true.payload or node.payload == {"crashed": True}, nid
            for e, te in zip(node.edges, true.edges):
                if (e[1], e[2]) in acc:
                    assert e == te, nid
