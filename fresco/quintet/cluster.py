"""QUINTET: five coordinators with disjoint write responsibilities over one
heterogeneous knowledge graph.

  Registrar  identities, candidates, slot keys          (rule R1)
  Treasurer  error-budget leases, grants, allocations   (rule R5)
  Recorder   slot leases and write-once results         (rules R3, R4)
  Arbiter    e-process confirmations and the frontier   (rules R2, R6)
  Archivist  anchor index, integrity scans, TWGR repair (corruption tolerance)

Each record type has exactly one writer, so every statistical invariant keeps a
single serialisation point; everything one coordinator reads from another is
write-once, so no cross-coordinator transaction is needed. Every write is stored at
the owner and two witness domains and anchored in the owner's and archivist's logs.

This module is the in-process form used by experiments; fresco/quintet/service.py
runs the same coordinators as separate networked processes.
"""

import math
from dataclasses import dataclass, replace

import numpy as np

from fresco.hkg import sign as sg
from fresco.hkg.graph import Fabric, Node, sha, canon
from fresco.hkg.repair import (RunParams, evaluate_confirmation, make_allocation, make_confirmation,
                               make_key, make_lease)


@dataclass
class QuintetConfig:
    workers: int = 4
    pool: int = 2                 # active candidates per worker
    budget: int = 3000            # oracle calls
    crash: float = 0.0            # executor crash probability (crash -> Y = 0, R4)
    stop_at_level: int = 0
    replicas: int = 2


class Quintet:
    def __init__(self, scenario, params, cfg, rng, device_seed=0):
        self.sc, self.cfg, self.rng = scenario, cfg, rng
        # executor devices sign their evidence; the manifest of their public keys is
        # published before the run (outside every coordinator domain)
        secrets = {f"w{w}": f"device-secret|{device_seed}|w{w}" for w in range(cfg.workers)}
        self.device = {w: sg.device_key(s) for w, s in secrets.items()}
        run_id = sha(canon(["run", params.run_key.hex(), device_seed]))
        self.p = replace(params, manifest=sg.make_manifest(run_id, secrets))
        self.nonce = 0
        self.fabric = Fabric(replicas=cfg.replicas)
        self.nodes = {}           # owner-side authoritative copies (what each coordinator serves)
        self.n_leases = 0
        self.lease_use = {}       # lease n -> registrations used
        self.next_j = 1
        self.slots = {}           # j -> next k
        self.results = {}         # j -> list of Result nodes in slot order
        self.status = {}          # j -> ACTIVE / CONFIRMED / CAPPED / PRUNED
        self.b_hat = math.inf
        self.frontier_seq = 0
        self.calls = 0

    # ---------------------------------------------------------- writes
    def _write(self, node):
        self.fabric.write(node)
        self.nodes[node.id] = node
        return node

    # Treasurer -------------------------------------------------------
    def grant(self, worker):
        self.n_leases += 1
        lease = self._write(make_lease(self.n_leases, self.p))
        self._write(Node("Grant", lease.key, {"worker": worker}, "treasurer",
                         (("of", "Lease", lease.key, lease.digest()),)))
        self.lease_use[self.n_leases] = 0
        return self.n_leases

    # Registrar + Treasurer --------------------------------------------
    def register(self, lease_n, level, content, worker="w0"):
        lease = self.nodes[("Lease", str(lease_n))]
        if self.lease_use[lease_n] >= self.p.lease_size or level >= self.b_hat:
            return None
        self.lease_use[lease_n] += 1
        j = str(self.next_j)
        self.next_j += 1
        self.nonce += 1
        req = {"lease": lease.key, "level": level, "content": content, "worker": worker, "nonce": self.nonce,
               "i": self.lease_use[lease_n]}
        req["sig"] = sg.sign_request(self.device[worker], self.p.manifest["run_id"], req)
        cand = self._write(Node("Candidate", j, req, "registrar",
                                (("funded_by", "Lease", lease.key, lease.digest()),)))
        self._write(make_allocation(cand, lease))
        self.slots[j], self.results[j], self.status[j] = 1, [], "ACTIVE"
        return j

    # Recorder + Registrar ----------------------------------------------
    def lease_and_run(self, worker, j):
        cand = self.nodes[("Candidate", j)]
        k = self.slots[j]
        self.slots[j] += 1
        sl = self._write(Node("SlotLease", f"{j}:{k}", {"worker": worker, "attempt": 0,
                                                       "token": sha(canon([j, k, worker]))}, "recorder",
                              (("for", "Candidate", j, cand.digest()),)))
        key = self._write(make_key(cand, k, self.p))
        self.calls += 1
        if self.rng.random() < self.cfg.crash:
            payload = {"crashed": True}            # executor lost: unsigned crash (R4), conservative
        else:
            y = int(self.sc.outcome(cand.payload["level"], cand.payload["content"], key.payload["key"]))
            sig = sg.sign_result(self.device[cand.payload["worker"]], self.p.manifest["run_id"], j, k, y,
                                 sg.request_hash(cand.payload), key.payload["key"])
            payload = {"y": y, "worker": cand.payload["worker"], "sig": sig}
        res = self._write(Node("Result", f"{j}:{k}", payload, "recorder",
                               (("for", "Candidate", j, cand.digest()), ("key", "Key", key.key, key.digest()),
                                ("lease", "SlotLease", sl.key, sl.digest()))))
        self.results[j].append(res)

    # Arbiter --------------------------------------------------------------
    def arbitrate(self, j):
        cand = self.nodes[("Candidate", j)]
        alloc = self.nodes[("Allocation", j)]
        ys = [r.payload.get("y") for r in self.results[j]]
        n, _, _, ok = evaluate_confirmation(alloc, ys, self.p.alpha, self.p.cap, self.p.bet_cap)
        if ok or n >= self.p.cap:
            conf = self._write(make_confirmation(cand, alloc, self.results[j], self.p))
            self.status[j] = "CONFIRMED" if ok else "CAPPED"
            level = cand.payload["level"]
            if ok and level < self.b_hat:
                self.b_hat = level
                self.frontier_seq += 1
                self._write(Node("Frontier", str(self.frontier_seq), {"b_hat": level, "witness": j}, "arbiter",
                                 (("witness", "Confirmation", conf.key, conf.digest()),)))
                for jj, st in self.status.items():
                    if st == "ACTIVE" and self.nodes[("Candidate", jj)].payload["level"] >= self.b_hat:
                        self.status[jj] = "PRUNED"

    # ---------------------------------------------------------- run
    def run(self):
        K = len(self.sc.levels)
        leases = {}
        mine = {w: [] for w in range(self.cfg.workers)}
        while self.calls < self.cfg.budget:
            active_levels = [k for k in range(1, K + 1) if k < self.b_hat]
            if not active_levels or (self.cfg.stop_at_level and self.b_hat <= self.cfg.stop_at_level):
                break
            for w in range(self.cfg.workers):
                mine[w] = [j for j in mine[w] if self.status[j] == "ACTIVE"]
                while len(mine[w]) < self.cfg.pool:
                    if w not in leases or self.lease_use[leases[w]] >= self.p.lease_size:
                        leases[w] = self.grant(f"w{w}")
                    level = int(self.rng.choice([k for k in range(1, K + 1) if k < self.b_hat] or [1]))
                    if level >= self.b_hat:
                        break
                    content = int(self.rng.integers(self.sc.levels[level - 1].space))
                    j = self.register(leases[w], level, content, worker=f"w{w}")
                    if j is None:
                        break
                    mine[w].append(j)
                for j in list(mine[w]):
                    if self.status[j] != "ACTIVE" or self.calls >= self.cfg.budget:
                        continue
                    self.lease_and_run(f"w{w}", j)
                    self.arbitrate(j)
        return {"b_hat": None if self.b_hat == math.inf else self.b_hat, "calls": self.calls,
                "records": len(self.fabric.truth)}

    def truth_report(self):
        conf = [(n.payload["level"], n.key) for nid, n in self.nodes.items()
                if nid[0] == "Confirmation" and n.payload["confirmed"]]
        return {"b_hat": min((lv for lv, _ in conf), default=None), "confirmed": sorted(conf)}
