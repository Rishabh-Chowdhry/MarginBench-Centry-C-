"""QUINTET as five networked coordinator services plus workers (stdlib HTTP + JSON).

    python -m fresco.quintet.service coordinator --role registrar --port 8101 --data /data
    python -m fresco.quintet.service worker --name w1 --budget 400
    python -m fresco.quintet.service scan            # ask the Archivist to run TWGR

Peers are given by the environment variable QUINTET_PEERS, a JSON object
role -> base URL (workers may be pointed at fault-injecting proxies). Run
parameters come from QUINTET_PARAMS (JSON with eps, lease_size, alpha, cap, run_key)
and the scenario from QUINTET_SCENARIO ("S1-dense" or "boundary-null").

Each coordinator is the single writer of its record types (see cluster.py). A write
is made durable locally (append-only JSONL, one file per domain), anchored in the
local log, and then replicated asynchronously: a copy and receipt to the two witness
domains and an anchor to the Archivist. Replication retries until it succeeds, so a
crashed or partitioned peer catches up when it returns. Outbound calls never hold
the coordinator lock. Lost slot leases expire into crash results (Y = 0, rule R4);
late results are fenced by the slot token and rejected.
"""

import argparse
import base64
import json
import os
import pathlib
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from fresco.hkg.graph import DOMAINS, DomainStore, Fabric, Node, canon, nid_str, sha, witnesses
from fresco.hkg import sign as sg
from fresco.hkg.repair import (TYPE_OWNER, RunParams, TWGRConfig, admissible, evaluate_confirmation, make_allocation,
                               make_confirmation, make_key, make_lease, report, robust_confirmed, twgr)
from fresco.sim.scenario import Level, Scenario

SCENARIOS = {
    "S1-dense": Scenario(levels=(Level(), Level(), Level(pi=0.3), Level(pi=0.5))),
    "boundary-null": Scenario(levels=tuple(Level(null_at_boundary=True) for _ in range(4))),
}


def env_params():
    p = json.loads(os.environ.get("QUINTET_PARAMS", "{}"))
    man = os.environ.get("QUINTET_MANIFEST")
    return RunParams(eps=p.get("eps", 0.05), lease_size=p.get("lease_size", 8),
                     run_key=p.get("run_key", "quintet-run-key").encode(), alpha=p.get("alpha", 0.2),
                     cap=p.get("cap", 40), manifest=json.loads(man) if man else None)


def env_peers():
    return json.loads(os.environ["QUINTET_PEERS"])


def b64(b):
    return base64.b64encode(b).decode()


def unb64(s):
    return base64.b64decode(s)


def parse_id(s):
    t, k = s.split(":", 1)
    return (t, k)


class Unavailable(Exception):
    pass


def call(url, path, body=None, timeout=5.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())
        except Exception:
            msg = {"error": str(e)}
        msg["_code"] = e.code
        return msg
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
        raise Unavailable(str(e)) from e


# ====================================================================== coordinator
class Coordinator:
    def __init__(self, role, data_dir, peers, params, scenario, slot_ttl=20.0):
        self.role, self.peers, self.p, self.sc = role, peers, params, scenario
        self.path = pathlib.Path(data_dir) / f"{role}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store = DomainStore.load(role, self.path) if self.path.exists() else DomainStore(role)
        self.lock = threading.RLock()
        self.scan_lock = threading.Lock()         # one TWGR scan at a time (Archivist)
        # one data queue and one control queue per peer: nothing waits behind another peer,
        # and copies never wait behind a control message (E12 defect D6)
        self.outbox = {(d, q): queue.Queue() for d in DOMAINS for q in ("data", "ctl")}
        self.pending = 0
        self.slot_ttl = slot_ttl
        self.slot_time = {}                       # (j, k) -> lease time (recorder)
        self.repairs = 0
        self.recovering = self.path.exists() and self._damaged()
        self._rebuild()
        for d in DOMAINS:
            for q in ("data", "ctl"):
                threading.Thread(target=self._replicator, args=(d, q), daemon=True).start()
        if self.recovering:
            threading.Thread(target=self._request_repair, daemon=True).start()
        else:
            self._resync()
        if role == "recorder":
            threading.Thread(target=self._expirer, daemon=True).start()

    # ------------------------------------------------------------ repair before serve
    def _damaged(self):
        """Self-check after a restart: every file line parses, every anchor link
        verifies, and every stored copy matches a digest this domain anchored for it.
        Any failure means the store may hold damaged evidence, so the coordinator must
        not act on it before a TWGR repair (E12 defect D4)."""
        bad = 0
        with open(self.path, "rb") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if "log" not in d:
                        base64.b64decode(d["b"], validate=True)
                except Exception:
                    bad += 1
        anchors = {}
        for i, dg, ok in self.store.anchor_entries():
            bad += not ok
            anchors.setdefault(i, set()).add(dg)
        bad += len(self.store.log) - len(self.store.anchor_entries())
        if self.role != "archivist":             # here every anchor was written together with a copy
            held = {nid_str(i) for i in self.store.blobs}
            bad += sum(1 for i in anchors if i not in held)
        for nid, b in self.store.blobs.items():
            try:
                n = Node.decode(b)
                bad += n.id != nid or n.digest() not in anchors.get(nid_str(nid), ())
            except ValueError:
                bad += 1
        return bad > 0

    def _request_repair(self):
        delay = 0.5
        while self.recovering:
            try:
                call(self.peers["archivist"], "/scan", {}, timeout=600) if self.role != "archivist" else self.op_scan({})
            except Unavailable:
                pass
            time.sleep(delay)
            delay = min(10.0, delay * 2)

    def op_recovered(self, body):
        """Called by the Archivist after a scan healed this domain."""
        with self.lock:
            was = self.recovering
            self.recovering = False
            self._rebuild()
        if was:
            self._resync()
        return 200, {}

    # ------------------------------------------------------------ state rebuild
    def _nodes(self, t):
        """Anchor-verified local records of type t (state is never rebuilt from damaged
        copies; E12 defect D7)."""
        return [n for n in (self.verified(nid) for nid in list(self.store.blobs) if nid[0] == t) if n is not None]

    def _rebuild(self):
        """Counters come from records present locally and from the Archivist's anchor
        index, so a coordinator restarted with a damaged store never reuses an id."""
        self.my_anchor = {}                       # id -> digests this domain anchored (verified links)
        for i, dg, ok in self.store.anchor_entries():
            if ok:
                self.my_anchor.setdefault(i, set()).add(dg)
        ids = set(self.store.blobs) | {parse_id(i) for i, _, _ in self.store.anchor_entries() if ":" in i}
        if self.role != "archivist" and "archivist" in self.peers:
            try:
                ids |= {parse_id(i) for i in call(self.peers["archivist"], "/ids", timeout=3).get("ids", [])}
            except Unavailable:
                pass
        # counters cover every record type keyed by the id, so a record lost from all
        # domains but survived by a neighbour never has its id reused (E12 defect D5)
        num = lambda ts: [int(k) for tt, k in ids if tt in ts and k.isdigit()]  # noqa: E731
        self.n_leases = max(num(("Lease", "Grant")), default=0)
        self.next_j = max(num(("Candidate", "Allocation", "Confirmation"))
                          + [int(j) for j, _ in self._slots(ids, ("SlotLease", "Key", "Result"))], default=0) + 1
        self.next_k = {}
        for j, kk in self._slots(ids, ("SlotLease", "Key", "Result")):
            self.next_k[j] = max(self.next_k.get(j, 1), kk + 1)
        if self.role == "recorder":               # open slots resume their expiry clock after a restart
            for j, kk in self._slots(ids):
                if ("Result", f"{j}:{kk}") not in ids:
                    self.slot_time.setdefault((j, kk), time.time())
        self.reserved = getattr(self, "reserved", {})   # (lease, i) -> request hash (Treasurer)
        self.funded = {}                          # (lease, i) -> j
        for n in self._nodes("Allocation"):
            self.funded[(n.payload["lease"], n.payload["i"])] = n.key
        self.lease_use = {}
        for (lease, i), _ in self.funded.items():
            self.lease_use[lease] = max(self.lease_use.get(lease, 0), i)
        self.b_hat = min((n.payload["b_hat"] for n in self._nodes("Frontier")), default=None)
        self.frontier_seq = max(num(("Frontier",)), default=0)

    def _resync(self):
        """After a restart the in-memory replication queues are gone: re-offer owned
        records to their witnesses (idempotent) and, at the Recorder, re-trigger
        arbitration for every candidate with results (idempotent at the Arbiter).
        Only records matching this domain's own verified anchor are re-offered, and
        without a receipt, so a locally damaged copy can never gain a vote elsewhere
        (E12 defect D3)."""
        mine = {}
        for i, d, ok in self.store.anchor_entries():
            if ok:
                mine.setdefault(i, set()).add(d)
        js = set()
        for nid, b in list(self.store.blobs.items()):
            try:
                n = Node.decode(b)
            except ValueError:
                continue
            if n.owner != self.role or n.id != nid or n.digest() not in mine.get(nid_str(nid), ()):
                continue
            for w in witnesses(nid, n.owner):
                self._enqueue(w, "/store", {"id": nid_str(nid), "b": b64(b), "receipt": False})
            if nid[0] == "Result":
                js.add(nid[1].rsplit(":", 1)[0])
        for j in sorted(js):
            self._enqueue("arbiter", "/arbitrate", {"j": j})

    @staticmethod
    def _slots(ids, types=("SlotLease",)):
        """Well-formed slot ids (j, k) of the given types; ids garbled by storage faults
        are skipped (E12 defect D1: a bit flip inside an id used to crash the restart)."""
        for tt, key in ids:
            if tt in types:
                j, _, kk = key.rpartition(":")
                if j.isdigit() and kk.isdigit():
                    yield j, int(kk)

    # ------------------------------------------------------------ storage
    def _persist(self, line):
        with open(self.path, "a") as f:
            f.write(json.dumps(line) + "\n")

    def _put_local(self, nid, b, anchor=True):
        """Write-once copy (+ anchor). Returns 'new', 'same' or 'conflict'."""
        with self.lock:
            cur = self.store.blobs.get(nid)
            if cur is not None:
                return "same" if cur == b else "conflict"
            self.store.put(nid, b)
            self._persist({"id": nid_str(nid), "b": b64(b)})
            if anchor:
                self._anchor_local(nid, Node.decode(b).digest())
            return "new"

    def _anchor_local(self, nid, digest):
        with self.lock:
            self.my_anchor.setdefault(nid_str(nid), set()).add(digest)
            self.store.append_anchor(nid, digest)
            self._persist({"log": self.store.log[-1]})

    def publish(self, node):
        """Owner write: local copy + anchor, then async copies/receipts to witnesses
        and an anchor at the Archivist."""
        b = node.encode()
        st = self._put_local(node.id, b)
        if st == "conflict":
            raise ValueError(f"write-once conflict for {node.id}")
        if st == "new":
            place = [node.owner] + witnesses(node.id, node.owner)
            for w in place[1:]:
                self._enqueue(w, "/store", {"id": nid_str(node.id), "b": b64(b)})
            if "archivist" not in place:
                self._enqueue("archivist", "/anchor", {"id": nid_str(node.id), "d": node.digest()})
        return node

    def _enqueue(self, role, path, body):
        with self.lock:
            self.pending += 1
        q = "data" if path in ("/store", "/anchor") else "ctl"
        self.outbox[(role, q)].put((path, body))

    def _replicator(self, role, q):
        """Deliver until accepted; a 5xx or an unreachable peer is retried with backoff.
        Data (copies, anchors) is retried until delivered. A control message (e.g. an
        arbitration trigger) is idempotent and re-triggered by workers, so it is dropped
        after a bounded number of attempts."""
        while True:
            path, body = self.outbox[(role, q)].get()
            delay, attempts = 0.1, 0
            while q == "data" or attempts < 8:
                attempts += 1
                try:
                    if call(self.peers[role], path, body, timeout=3).get("_code", 200) < 500:
                        break
                except Exception:
                    pass
                time.sleep(delay)
                delay = min(2.0, delay * 2)
            with self.lock:
                self.pending -= 1

    # ------------------------------------------------------------ peer reads
    def verified(self, nid):
        """The local copy of nid only if it matches a digest this domain anchored when it
        stored it; damaged or tampered copies are never served or used (E12 defect D6)."""
        b = self.store.blobs.get(nid)
        if b is None:
            return None
        try:
            n = Node.decode(b)
        except ValueError:
            return None
        return n if n.id == nid and n.digest() in self.my_anchor.get(nid_str(nid), ()) else None

    def fetch(self, nid):
        """A record from this domain or its owner/witnesses, anchor-verified at the source."""
        n = self.verified(nid)
        if n is not None:
            return n
        owner = TYPE_OWNER[nid[0]]
        for d in [owner] + witnesses(nid, owner):
            if d == self.role:
                continue
            try:
                r = call(self.peers[d], "/node?id=" + nid_str(nid), timeout=3)
            except Unavailable:
                continue
            if "b" in r:
                try:
                    n = Node.decode(unb64(r["b"]))
                    if n.id == nid:
                        return n
                except ValueError:
                    continue
        return None

    # ------------------------------------------------------------ role operations
    def op(self, path, body):
        name = path.strip("/").replace("/", "_")
        h = getattr(self, "op_" + name, None)
        if h is None:
            return 404, {"error": "unknown operation"}
        if self.recovering and name not in ("store", "anchor", "repair", "rebuild", "recovered", "scan"):
            return 503, {"error": "recovering: waiting for TWGR repair"}
        return h(body)

    # common to all domains
    def op_store(self, body):
        st = self._put_local(parse_id(body["id"]), unb64(body["b"]), anchor=body.get("receipt", True))
        return (409 if st == "conflict" else 200), {"result": st}

    def op_anchor(self, body):
        self._anchor_local(parse_id(body["id"]), body["d"])
        return 200, {}

    def op_repair(self, body):
        nid, b = parse_id(body["id"]), unb64(body["b"])
        with self.lock:
            if self.store.blobs.get(nid) != b:
                self.store.repair_put(nid, b)
                self._persist({"id": body["id"], "b": body["b"]})
                self.repairs += 1
        return 200, {}

    def op_rebuild(self, body):
        with self.lock:
            self._rebuild()
        return 200, {}

    # Treasurer
    def op_grant(self, body):
        with self.lock:
            self.n_leases += 1
            n = self.n_leases
        lease = self.publish(make_lease(n, self.p))
        self.publish(Node("Grant", lease.key, {"worker": body["worker"]}, "treasurer",
                          (("of", "Lease", lease.key, lease.digest()),)))
        return 200, {"lease": n}

    def op_reserve(self, body):
        """The device chooses its index i within the lease it holds (it signs it); the
        Treasurer admits each (lease, i) for one request only, so sum a_j <= eps."""
        lease_key, i, rh = str(body["lease"]), int(body["i"]), body["req"]
        lease = self.fetch(("Lease", lease_key))
        with self.lock:
            held = self.reserved.setdefault((lease_key, i), rh)
            if lease is None or not 1 <= i <= self.p.lease_size or held != rh:
                return 409, {"error": "lease exhausted or index taken"}
        return 200, {"lease": b64(lease.encode())}

    def op_allocate(self, body):
        cand = Node.decode(unb64(body["candidate"]))
        lease = self.fetch(("Lease", cand.payload["lease"]))
        key = (cand.payload["lease"], cand.payload["i"])
        with self.lock:
            if self.funded.get(key, cand.key) != cand.key:      # one allocation per (lease, i): sum a_j <= eps
                return 409, {"error": "slot of lease already funded"}
            self.funded[key] = cand.key
        self.publish(make_allocation(cand, lease))
        return 200, {}

    # Registrar
    def op_register(self, body):
        req = body.get("req", {})
        probe = Node("Candidate", "0", req, "registrar")
        if self.p.manifest and admissible(probe, {}, self.p) != "signed":
            return 403, {"error": "registration request not signed by a manifest device"}
        try:
            r = call(self.peers["treasurer"], "/reserve", {"lease": req.get("lease"), "i": req.get("i"),
                                                           "req": sg.request_hash(req)})
        except Unavailable:
            return 503, {"error": "treasurer unavailable"}
        if "lease" not in r:
            return 409, r
        lease = Node.decode(unb64(r["lease"]))
        with self.lock:
            j = str(self.next_j)
            self.next_j += 1
        cand = self.publish(Node("Candidate", j, req, "registrar",
                                 (("funded_by", "Lease", lease.key, lease.digest()),)))
        try:
            a = call(self.peers["treasurer"], "/allocate", {"candidate": b64(cand.encode())})
        except Unavailable:
            return 503, {"error": "treasurer unavailable", "j": j}
        if a.get("_code", 200) != 200:
            return 409, a
        return 200, {"j": j}

    def op_key(self, body):
        cand = self.fetch(("Candidate", body["j"]))
        if cand is None:
            return 404, {"error": "unknown candidate"}
        key = make_key(cand, int(body["k"]), self.p)
        try:
            self.publish(key)
        except ValueError:
            return 409, {"error": "key conflict"}
        return 200, {"b": b64(key.encode())}

    # Recorder
    def op_slot(self, body):
        j = body["j"]
        cand = self.fetch(("Candidate", j))
        if cand is None:
            return 404, {"error": "unknown candidate"}
        with self.lock:
            k = self.next_k.get(j, 1)
            if k > self.p.cap:
                return 409, {"error": "cap reached"}
            self.next_k[j] = k + 1
            self.slot_time[(j, k)] = time.time()
        token = sha(canon([j, k, body["worker"], time.time()]))
        sl = self.publish(Node("SlotLease", f"{j}:{k}", {"worker": body["worker"], "token": token}, "recorder",
                               (("for", "Candidate", j, cand.digest()),)))
        try:
            kr = call(self.peers["registrar"], "/key", {"j": j, "k": k})
        except Unavailable:
            kr = {}
        if "b" not in kr:                         # no key: the slot will expire into a crash (R4)
            return 503, {"error": "registrar unavailable"}
        key = Node.decode(unb64(kr["b"]))
        return 200, {"k": k, "token": sl.payload["token"], "key": key.payload["key"],
                     "level": cand.payload["level"], "content": cand.payload["content"]}

    def _record(self, j, k, payload):
        nid = ("Result", f"{j}:{k}")
        sl = self.fetch(("SlotLease", f"{j}:{k}"))
        cand = self.fetch(("Candidate", j))
        key = self.fetch(("Key", f"{j}:{k}"))
        if sl is None or cand is None:
            return 404, {"error": "unknown slot"}
        edges = [("for", "Candidate", j, cand.digest()), ("lease", "SlotLease", sl.key, sl.digest())]
        if key is not None:
            edges.insert(1, ("key", "Key", key.key, key.digest()))
        node = Node("Result", f"{j}:{k}", payload, "recorder", tuple(edges))
        cur = self.store.blobs.get(nid)
        if cur is not None:
            return (200 if cur == node.encode() else 409), {"result": "exists"}
        if self._known_elsewhere(nid) is not False:   # lost locally but may exist elsewhere: repair first
            return 409, {"result": "exists elsewhere or unknown"}
        self.publish(node)
        with self.lock:
            self.slot_time.pop((j, k), None)
        self._enqueue("arbiter", "/arbitrate", {"j": j})
        return 200, {"result": "recorded"}

    def op_result(self, body):
        j, k = body["j"], int(body["k"])
        sl = self.fetch(("SlotLease", f"{j}:{k}"))
        if sl is None or sl.payload["token"] != body["token"]:
            return 403, {"error": "fenced: stale or unknown slot token"}
        payload = {"y": int(body["y"])}
        if body.get("sig") is not None:
            payload.update(worker=body.get("worker"), sig=body.get("sig"))
        if self.p.manifest:
            cand = self.fetch(("Candidate", j))
            probe = Node("Result", f"{j}:{k}", payload, "recorder")
            if cand is None or admissible(probe, {("Candidate", j): cand}, self.p) != "signed":
                return 403, {"error": "result not signed by the candidate's device"}
        return self._record(j, k, payload)

    def _expirer(self):
        while True:
            time.sleep(1.0)
            now = time.time()
            with self.lock:
                due = [s for s, t in self.slot_time.items() if now - t > self.slot_ttl]
            for j, k in due:
                nid = ("Result", f"{j}:{k}")
                if nid not in self.store.blobs:
                    known = self._known_elsewhere(nid)
                    if known is None:
                        continue                  # cannot tell: postpone (safety over liveness)
                    if not known:
                        self._record(j, k, {"crashed": True})
                with self.lock:
                    self.slot_time.pop((j, k), None)

    def _known_elsewhere(self, nid):
        """Whether any other domain holds a copy or an anchor of nid (None: unknown).
        A Recorder that lost its local copy must never expire a slot whose result
        exists elsewhere: that would fabricate a crash result (E12 defect D2)."""
        try:
            if call(self.peers["archivist"], "/anchored?id=" + nid_str(nid), timeout=3).get("anchored"):
                return True
        except Unavailable:
            return None
        for d in witnesses(nid, self.role):
            try:
                if "b" in call(self.peers[d], "/node?id=" + nid_str(nid), timeout=3):
                    return True
            except Unavailable:
                return None
        return False

    def op_results(self, body):
        j = body["j"]
        out, k = [], 1
        while ("Result", f"{j}:{k}") in self.store.blobs:   # in-order prefix of intact results only:
            b = self.store.blobs[("Result", f"{j}:{k}")]    # a damaged one is a gap (E12 defect D6)
            try:                                            # verified = matches our write-time anchor
                if Node.decode(b).digest() not in self.my_anchor.get(f"Result:{j}:{k}", ()):
                    break
            except ValueError:
                break
            out.append(b64(b))
            k += 1
        return 200, {"results": out}

    # Arbiter
    def op_arbitrate(self, body):
        j = body["j"]
        if ("Confirmation", j) in self.store.blobs:
            return 200, {"status": "DECIDED"}
        cand, alloc = self.fetch(("Candidate", j)), self.fetch(("Allocation", j))
        try:
            rs = call(self.peers["recorder"], "/results", {"j": j}).get("results", [])
        except Unavailable:
            return 503, {"error": "recorder unavailable"}
        if cand is None or alloc is None:
            return 404, {"error": "unknown candidate"}
        try:
            results = [Node.decode(unb64(r)) for r in rs]
        except ValueError as e:
            return 422, {"error": f"undecodable result: {e}"}
        n, _, _, ok = evaluate_confirmation(alloc, [r.payload.get("y") for r in results], self.p.alpha,
                                            self.p.cap, self.p.bet_cap)
        if ok and not robust_confirmed(alloc, results, self.p):
            ok = False                            # unsigned crash slots are unknown, not 0 (TWGR-S rule)
        if not ok and n < self.p.cap:
            return 200, {"status": "ACTIVE"}
        try:
            conf = self.publish(make_confirmation(cand, alloc, results, self.p, robust=True))
        except ValueError:
            return 200, {"status": "DECIDED"}
        if conf.payload["confirmed"]:
            level = cand.payload["level"]
            with self.lock:
                improve = self.b_hat is None or level < self.b_hat
                if improve:
                    self.b_hat = level
                    self.frontier_seq += 1
                    seq = self.frontier_seq
            if improve:
                self.publish(Node("Frontier", str(seq), {"b_hat": level, "witness": j}, "arbiter",
                                  (("witness", "Confirmation", conf.key, conf.digest()),)))
        return 200, {"status": "CONFIRMED" if conf.payload["confirmed"] else "CAPPED"}

    def op_status(self, body):
        j = body["j"]
        n = self.verified(("Confirmation", j))
        if n is not None:
            return 200, {"status": "CONFIRMED" if n.payload.get("confirmed") else "CAPPED", "b_hat": self.b_hat}
        return 200, {"status": "ACTIVE", "b_hat": self.b_hat}

    # Archivist
    def op_scan(self, body):
        with self.scan_lock:
            return self._scan()

    def _scan(self):
        """Pull every domain, run TWGR, push healed copies back. Unreachable domains
        are treated as empty (their records rely on the other domains)."""
        fab = Fabric()
        reach = {}
        for d in DOMAINS:
            try:
                dump = call(self.peers[d], "/dump", timeout=30) if d != self.role else self._dump()
                st = DomainStore(d)
                st.blobs = {parse_id(i): unb64(b) for i, b in dump["blobs"].items()}
                st.log = dump["log"]
                fab.stores[d] = st
                reach[d] = True
            except (Unavailable, KeyError):
                reach[d] = False
        before = {d: dict(st.blobs) for d, st in fab.stores.items()}
        status, acc = twgr(fab, self.p, TWGRConfig(authenticate=bool(self.p.manifest)), heal=True)
        pushed = 0
        for d, st in fab.stores.items():
            if not reach[d]:
                continue
            for nid, b in st.blobs.items():
                if before[d].get(nid) != b:
                    try:
                        if d == self.role:
                            self.op_repair({"id": nid_str(nid), "b": b64(b)})
                        else:
                            call(self.peers[d], "/repair", {"id": nid_str(nid), "b": b64(b)})
                        pushed += 1
                    except Unavailable:
                        pass
        counts = {}
        for s in status.values():
            counts[s] = counts.get(s, 0) + 1
        for d in DOMAINS:                       # healed domains may serve again
            if reach[d]:
                try:
                    self.op_recovered({}) if d == self.role else call(self.peers[d], "/recovered", {})
                except Unavailable:
                    pass
        rep = report(acc)
        accepted = {nid_str(i): n.digest() for i, n in acc.items()}
        return 200, {"status": counts, "report": rep, "healed_copies": pushed, "reachable": reach,
                     "accepted": accepted}

    def _dump(self):
        with self.lock:
            return {"blobs": {nid_str(i): b64(b) for i, b in self.store.blobs.items()}, "log": list(self.store.log)}

    def op_ids(self, body):
        with self.lock:
            return 200, {"ids": sorted({i for i, _, _ in self.store.anchor_entries()})}


def make_handler(coord):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            path, _, qs = self.path.partition("?")
            q = dict(kv.split("=", 1) for kv in qs.split("&") if "=" in kv)
            if path == "/health":
                return self._send(200, {"role": coord.role, "records": len(coord.store.blobs),
                                        "recovering": coord.recovering,
                                        "log": len(coord.store.log), "pending": coord.pending,
                                        "repairs": coord.repairs, "b_hat": coord.b_hat})
            if path == "/dump":
                return self._send(200, coord._dump())
            if path == "/node":
                n = coord.verified(parse_id(q.get("id", ":")))
                return self._send(200 if n is not None else 404, {"b": b64(n.encode())} if n is not None else {})
            if path == "/anchored":
                i = q.get("id", "")
                return self._send(200, {"anchored": any(e[0] == i for e in coord.store.anchor_entries())})
            if path == "/ids":
                return self._send(*coord.op_ids({}))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                code, obj = coord.op(self.path, body)
            except Exception as e:                   # surfaced to the caller, never crashes the server
                code, obj = 500, {"error": f"{type(e).__name__}: {e}"}
            self._send(code, obj)
    return H


# ====================================================================== worker
class Worker:
    """An executor device: obtains leases, registers candidates, runs slots and
    reports results. The oracle is the synthetic scenario (ground truth known)."""

    def __init__(self, name, peers, params, scenario, budget, seed, pool=2, timeout=5.0, wall=900.0, secret=None):
        self.name, self.peers, self.p, self.sc = name, peers, params, scenario
        self.budget, self.pool, self.timeout, self.wall = budget, pool, timeout, wall
        self.rng = np.random.default_rng(seed)
        self.calls, self.errors, self.lease = 0, 0, None
        secret = secret or os.environ.get("QUINTET_DEVICE_SECRET")
        self.sk = sg.device_key(secret) if secret else None
        self.run_id = (params.manifest or {}).get("run_id")
        self.lease_i, self.nonce, self.reqs = 0, 0, {}
        self.codes = {}                           # non-200 response codes seen, by code
        self.mine = []

    def _call(self, role, path, body):
        for attempt in range(4):
            try:
                r = call(self.peers[role], path, body, timeout=self.timeout)
                if "_code" in r:
                    self.codes[str(r["_code"])] = self.codes.get(str(r["_code"]), 0) + 1
                return r
            except Unavailable:
                self.errors += 1
                time.sleep(0.2 * 2 ** attempt)
        return {"_code": 599}

    def run(self):
        K = len(self.sc.levels)
        t0 = time.time()
        while self.calls < self.budget and time.time() - t0 < self.wall:
            b_hat = self._call("arbiter", "/status", {"j": "0"}).get("b_hat")
            top = (b_hat or K + 1) - 1
            if top < 1:
                break
            self.mine = [j for j in self.mine
                         if self._call("arbiter", "/status", {"j": j}).get("status") == "ACTIVE"]
            while len(self.mine) < self.pool:
                if self.lease is None or self.lease_i >= self.p.lease_size:
                    self.lease = self._call("treasurer", "/grant", {"worker": self.name}).get("lease")
                    self.lease_i = 0
                    if self.lease is None:
                        break
                level = int(self.rng.integers(1, top + 1))
                content = int(self.rng.integers(self.sc.levels[level - 1].space))
                self.lease_i += 1
                self.nonce += 1
                req = {"lease": str(self.lease), "level": level, "content": content, "worker": self.name,
                       "nonce": self.nonce, "i": self.lease_i}
                if self.sk is not None:
                    req["sig"] = sg.sign_request(self.sk, self.run_id, req)
                r = self._call("registrar", "/register", {"req": req})
                if "j" in r and r.get("_code", 200) == 200:
                    self.mine.append(r["j"])
                    self.reqs[r["j"]] = sg.request_hash(req)
                elif r.get("_code") == 409:
                    self.lease = None
                else:
                    break
            for j in list(self.mine):
                s = self._call("recorder", "/slot", {"j": j, "worker": self.name})
                if s.get("_code") == 409:            # cap reached: make sure it gets decided, then drop it
                    self._call("arbiter", "/arbitrate", {"j": j})
                    self.mine.remove(j)
                    continue
                if "k" not in s:
                    time.sleep(0.05)
                    continue
                self.calls += 1
                y = int(self.sc.outcome(s["level"], s["content"], s["key"]))
                body = {"j": j, "k": s["k"], "token": s["token"], "y": y, "worker": self.name}
                if self.sk is not None:
                    body["sig"] = sg.sign_result(self.sk, self.run_id, j, s["k"], y, self.reqs[j], s["key"])
                self._call("recorder", "/result", body)
        return {"worker": self.name, "calls": self.calls, "errors": self.errors, "codes": self.codes}


# ====================================================================== CLI
def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coordinator")
    c.add_argument("--role", choices=DOMAINS, required=True)
    c.add_argument("--port", type=int, required=True)
    c.add_argument("--data", default="/data")
    c.add_argument("--slot-ttl", type=float, default=20.0)
    w = sub.add_parser("worker")
    w.add_argument("--name", required=True)
    w.add_argument("--budget", type=int, default=300)
    w.add_argument("--seed", type=int, default=0)
    sub.add_parser("scan")
    a = ap.parse_args(argv)
    sc = SCENARIOS[os.environ.get("QUINTET_SCENARIO", "S1-dense")]
    if a.cmd == "coordinator":
        coord = Coordinator(a.role, a.data, env_peers(), env_params(), sc, slot_ttl=a.slot_ttl)
        srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(coord))
        print(f"{a.role} listening on {a.port} ({len(coord.store.blobs)} records loaded)", flush=True)
        srv.serve_forever()
    elif a.cmd == "worker":
        out = Worker(a.name, env_peers(), env_params(), sc, a.budget, a.seed).run()
        print(json.dumps(out), flush=True)
    else:
        r = call(env_peers()["archivist"], "/scan", {}, timeout=600)
        r.pop("accepted", None)
        print(json.dumps(r), flush=True)


if __name__ == "__main__":
    sys.exit(main())
