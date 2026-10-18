"""Heterogeneous knowledge graph (HKG): typed, write-once, hash-anchored records
spread over five failure domains (the five coordinators).

Every record is a typed node (type, key, payload, owner, edges). An edge stores the
*digest* of its target, so a node vouches for its neighbours' content. Each node is
stored as bytes at its owner and at two witness domains, and its digest is appended
to the owner's and the archivist's hash-chained anchor logs. Storage is a plain
bytes map per domain, so corruption of any stored item (bit flips, truncation,
deletion, format-valid tampering) can be injected and later repaired by TWGR
(fresco/hkg/repair.py).
"""

import base64
import hashlib
import json
from dataclasses import dataclass, field

DOMAINS = ("registrar", "treasurer", "recorder", "arbiter", "archivist")


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def sha(b):
    return hashlib.sha256(b).hexdigest()[:32]


@dataclass(frozen=True)
class Node:
    type: str
    key: str
    payload: dict
    owner: str
    edges: tuple = ()          # ((edge_type, target_type, target_key, target_digest), ...)

    @property
    def id(self):
        return (self.type, self.key)

    def encode(self):
        return canon({"t": self.type, "k": self.key, "p": self.payload, "o": self.owner,
                      "e": [list(e) for e in self.edges]})

    def digest(self):
        return sha(self.encode())

    @staticmethod
    def decode(b):
        """Parse stored bytes; raises ValueError if they are not a well-formed node."""
        try:
            d = json.loads(b.decode())
            node = Node(d["t"], d["k"], d["p"], d["o"], tuple(tuple(e) for e in d["e"]))
        except Exception as exc:                       # malformed, truncated, wrong types
            raise ValueError(f"undecodable node: {exc}") from None
        if not isinstance(node.payload, dict) or node.owner not in DOMAINS:
            raise ValueError("malformed node")
        for e in node.edges:
            if len(e) != 4 or not all(isinstance(x, str) for x in e):
                raise ValueError("malformed edge")
        return node


def nid_str(nid):
    return f"{nid[0]}:{nid[1]}"


@dataclass
class DomainStore:
    """One failure domain: node copies (id -> bytes) and a hash-chained anchor log."""
    name: str
    blobs: dict = field(default_factory=dict)
    log: list = field(default_factory=list)     # encoded entries {"s", "id", "d", "c"}

    def put(self, nid, b):
        if nid in self.blobs:                   # write-once: never overwrite an existing record
            return False
        self.blobs[nid] = b
        return True

    def repair_put(self, nid, b):
        self.blobs[nid] = b

    def append_anchor(self, nid, digest):
        prev = json.loads(self.log[-1])["c"] if self.log else "genesis"
        chain = sha(canon([prev, nid_str(nid), digest]))
        self.log.append(json.dumps({"s": len(self.log), "id": nid_str(nid), "d": digest, "c": chain}))

    def anchor_entries(self):
        """Decodable anchor-log entries as (id string, digest, chain_ok)."""
        out, prev = [], "genesis"
        for raw in self.log:
            try:
                e = json.loads(raw)
                ok = e["c"] == sha(canon([prev, e["id"], e["d"]]))
                prev = e["c"]
                out.append((e["id"], e["d"], ok))
            except Exception:
                prev = None
        return out

    # persistence for the real-environment deployment (one file per domain)
    def save(self, path):
        with open(path, "w") as f:
            for nid, b in self.blobs.items():
                f.write(json.dumps({"id": nid_str(nid), "b": base64.b64encode(b).decode()}) + "\n")
            for raw in self.log:
                f.write(json.dumps({"log": raw}) + "\n")

    @classmethod
    def load(cls, name, path):
        st = cls(name)
        with open(path, "rb") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if "log" in d:
                        st.log.append(d["log"])
                    else:
                        t, k = d["id"].split(":", 1)
                        st.blobs[(t, k)] = base64.b64decode(d["b"])
                except Exception:
                    continue                    # a corrupted line is a lost item, repaired later
        return st


def witnesses(nid, owner, r=2):
    """Deterministic witness placement: r distinct domains other than the owner,
    chosen by rotating the domain ring by a hash of the node id."""
    others = [d for d in DOMAINS if d != owner]
    start = int(sha(canon(list(nid))), 16) % len(others)
    return [others[(start + i) % len(others)] for i in range(r)]


class Fabric:
    """In-process view of all five domain stores (the experiment substrate). The
    networked deployment implements the same three operations over HTTP."""

    def __init__(self, replicas=2, archivist_anchor=True):
        self.stores = {d: DomainStore(d) for d in DOMAINS}
        self.replicas = replicas
        self.archivist_anchor = archivist_anchor
        self.truth = {}                         # ground truth for evaluation only

    def placement(self, node):
        return [node.owner] + witnesses(node.id, node.owner, self.replicas)

    def write(self, node):
        b = node.encode()
        if self.truth.get(node.id, b) != b:
            raise ValueError(f"write-once violation for {node.id}")
        self.truth[node.id] = b
        for d in self.placement(node):
            self.stores[d].put(node.id, b)
        dg = node.digest()
        self.stores[node.owner].append_anchor(node.id, dg)
        if self.archivist_anchor and node.owner != "archivist":
            self.stores["archivist"].append_anchor(node.id, dg)
        return dg

    def all_ids(self):
        ids = set(self.truth)
        for st in self.stores.values():
            ids.update(st.blobs)
        return ids
