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
