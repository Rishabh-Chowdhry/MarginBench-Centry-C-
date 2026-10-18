import json
import pathlib
import sys
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.hkg.graph import DOMAINS  # noqa: E402
from fresco.quintet.service import SCENARIOS, Coordinator, Worker, call, make_handler  # noqa: E402
from fresco.hkg.repair import RunParams  # noqa: E402

P = RunParams(eps=0.05, lease_size=8, run_key=b"svc-test", alpha=0.2, cap=40)


def start_cluster(tmp_path):
    servers, peers = {}, {}
    for r in DOMAINS:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        servers[r] = srv
        peers[r] = f"http://127.0.0.1:{srv.server_address[1]}"
    coords = {}
    for r in ("archivist",) + tuple(d for d in DOMAINS if d != "archivist"):
        coords[r] = Coordinator(r, tmp_path / r, peers, P, SCENARIOS["S1-dense"], slot_ttl=1.0)
        servers[r].RequestHandlerClass = make_handler(coords[r])
        threading.Thread(target=servers[r].serve_forever, daemon=True).start()
    return servers, peers, coords


def drain(coords, limit=30):
    t0 = time.time()
    while time.time() - t0 < limit:
        if all(c.pending == 0 for c in coords.values()):
            return True
        time.sleep(0.1)
    return False


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("quintet")
    servers, peers, coords = start_cluster(tmp)
    ws = [Worker(f"w{i}", peers, P, SCENARIOS["S1-dense"], budget=80, seed=i) for i in range(3)]
    th = [threading.Thread(target=w.run) for w in ws]
    for t in th:
        t.start()
    for t in th:
        t.join(120)
    time.sleep(2.5)                                   # let open slots expire
    assert drain(coords)
    yield tmp, servers, peers, coords, ws
    for s in servers.values():
        s.shutdown()


def test_service_run_is_fully_verified(cluster):
    _, _, peers, coords, ws = cluster
    assert all(w.calls >= 80 for w in ws)
    r = call(peers["archivist"], "/scan", {}, timeout=60)
    assert set(r["status"]) == {"VERIFIED"}
    assert r["report"]["b_hat"] == coords["arbiter"].b_hat


def test_results_are_write_once_and_fenced(cluster):
    _, _, peers, coords, _ = cluster
    rec = coords["recorder"]
    nid = next(i for i in rec.store.blobs if i[0] == "Result")
    j, k = nid[1].rsplit(":", 1)
    r = call(peers["recorder"], "/result", {"j": j, "k": k, "token": "forged", "y": 1})
    assert r["_code"] == 403
    sl = rec.fetch(("SlotLease", nid[1]))
    before = rec.store.blobs[nid]
    call(peers["recorder"], "/result", {"j": j, "k": k, "token": sl.payload["token"], "y": 1})
    assert rec.store.blobs[nid] == before


def test_restart_survives_garbled_ids(cluster, tmp_path):
    """Regression for E12 defect D1: a bit flip inside a stored id crashed the restart."""
    tmp, _, peers, _, _ = cluster
    src = tmp / "recorder" / "recorder.jsonl"
    lines = src.read_text().splitlines()
    garbled = []
    for ln in lines[:50]:
        d = json.loads(ln)
        if "id" in d and d["id"].startswith("SlotLease:"):
            d["id"] = d["id"] + "w"
        garbled.append(json.dumps(d))
    (tmp_path / "recorder").mkdir()
    (tmp_path / "recorder" / "recorder.jsonl").write_text("\n".join(garbled + lines[50:]) + "\n")
    c = Coordinator("recorder", tmp_path / "recorder", peers, P, SCENARIOS["S1-dense"])
    assert c.next_k


def test_restarted_recorder_never_fabricates_crash_results(cluster):
    """Regression for E12 defect D2: a slot whose Result was lost locally (but exists at
    witnesses and in the Archivist's anchors) must not expire into a crash result."""
    _, _, _, coords, _ = cluster
    rec = coords["recorder"]
    nid = next(i for i, b in rec.store.blobs.items() if i[0] == "Result" and b'"y"' in b)
    true = rec.store.blobs.pop(nid)
    j, k = nid[1].rsplit(":", 1)
    n_log = len(rec.store.log)
    with rec.lock:
        rec.slot_time[(j, int(k))] = 0.0
    time.sleep(2.5)
    assert rec.store.blobs.get(nid) in (None, true) and len(rec.store.log) == n_log   # absent or healed, never a crash
    rec.store.blobs[nid] = true


def test_damaged_restart_waits_for_repair(cluster, tmp_path):
    """Regression for E12 defect D4: a coordinator restarted on a damaged store must
    refuse role operations until a TWGR scan has healed it."""
    tmp, _, peers, _, _ = cluster
    lines = (tmp / "arbiter" / "arbiter.jsonl").read_text().splitlines()
    (tmp_path / "arbiter").mkdir()
    (tmp_path / "arbiter" / "arbiter.jsonl").write_text("\n".join(lines[1:]) + "\n")   # first record lost
    c = Coordinator("arbiter", tmp_path / "arbiter", {**peers, "archivist": "http://127.0.0.1:9"}, P,
                    SCENARIOS["S1-dense"])
    assert c.recovering
    code, _ = c.op("/arbitrate", {"j": "1"})
    assert code == 503
    c.op("/recovered", {})
    assert not c.recovering
