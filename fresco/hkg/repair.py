"""TWGR — Typed-Witness Graph Repair.

For every record x of the heterogeneous graph, TWGR gathers three independent kinds
of evidence about x's true content:

  (W1) copies      — the bytes stored at x's owner and its witness domains;
  (W2) anchors     — digests of x recorded in the owner's and archivist's hash-chained
                     anchor logs and in the edges of every node that references x;
  (W3) derivations — x recomputed from *already verified* records of other types
                     (e.g. a budget lease from its index, an allocation from its lease,
                     a slot key from the run key, a confirmation from its results).

Evidence is aggregated into one vote per failure domain (domain-distinct quorum). A
value is accepted only if (a) a strict majority of voting domains, and at least two,
agree on its digest and some copy or derivation has that digest, or (b) it is a
derivation from verified inputs (a pure function, hence exact). Otherwise x is
QUARANTINED and the consumer applies the direction-aware rule: a quarantined result
counts as a crashed slot (Y = 0 for confirmation, Z = 1 for audits), a quarantined
lease as fully spent, a quarantined allocation or candidate as unconfirmable. Records
are processed in type-dependency order so derivations only use verified inputs, and
healed bytes are written back to every placement domain.

Guarantees (proved in docs/stage7_quintet_hkg_twgr.md): no fabrication while fewer
than half of the voting domains are corrupted for a record (collision resistance),
validity of every confirmation computed from the repaired graph, and termination in
one ordered pass plus one confirmation re-derivation.
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from fresco.eprocess import EProcess, PlugInKelly
from fresco.hkg.graph import DOMAINS, Node, sha, canon

VERIFIED, REPAIRED, RECONSTRUCTED, QUARANTINED, BEST_EFFORT, LOST = (
    "VERIFIED", "REPAIRED", "RECONSTRUCTED", "QUARANTINED", "BEST_EFFORT", "LOST")

TYPE_OWNER = {"Lease": "treasurer", "Grant": "treasurer", "Allocation": "treasurer",
              "Candidate": "registrar", "Key": "registrar",
              "SlotLease": "recorder", "Result": "recorder",
              "Confirmation": "arbiter", "Frontier": "arbiter"}
TYPE_ORDER = ["Lease", "Grant", "Candidate", "Allocation", "SlotLease", "Key", "Result",
              "Confirmation", "Frontier"]


@dataclass
class TWGRConfig:
    use_replicas: bool = True       # W1 beyond the owner copy
    use_log_anchors: bool = True    # W2 from anchor logs
    use_edge_anchors: bool = True   # W2 from referencing nodes
    use_derivation: bool = True     # W3
    domain_votes: bool = True       # one vote per failure domain (False: one per item)
    quarantine: bool = True         # False: naive best effort (owner copy, else any copy)
    copy_votes: bool = False        # True: plain replica-majority voting (copies vote for themselves)
    min_support: int = 2            # distinct domains that must support the accepted digest


@dataclass
class RunParams:
    """What derivations need: the error-budget policy and the run key."""
    eps: float
    lease_size: int
    run_key: bytes
    alpha: float
    cap: int
    bet_cap: float = 0.5


def prf_key(run_key, j, k):
    import hmac
    import hashlib
    return int.from_bytes(hmac.new(run_key, f"slot|{j}|{k}".encode(), hashlib.sha256).digest()[:8], "big")


# ---------------------------------------------------------------- node constructors
# Shared by the coordinators (to write) and by TWGR (to derive), so a derivation is
# byte-identical to the original whenever its inputs are the true records.
def make_lease(n, params):
    return Node("Lease", str(n), {"n": n, "amount": params.eps / (n * (n + 1)), "size": params.lease_size},
                "treasurer")


def make_allocation(cand, lease):
    return Node("Allocation", cand.key,
                {"a": lease.payload["amount"] / lease.payload["size"], "lease": lease.key, "i": cand.payload["i"]},
                "treasurer", (("for", "Candidate", cand.key, cand.digest()), ("funds", "Lease", lease.key, lease.digest())))


def make_key(cand, k, params):
    return Node("Key", f"{cand.key}:{k}", {"key": prf_key(params.run_key, cand.key, k)}, "registrar",
                (("of", "Candidate", cand.key, cand.digest()),))


def evaluate_confirmation(alloc, results, alpha, cap, bet_cap=0.5):
    """Re-run the Arbiter's e-process over the in-order prefix. results: list of y or
    None (crashed / quarantined -> 0). Returns (n, s, max_log_e, confirmed)."""
    ep = EProcess(alpha, PlugInKelly(bet_cap))
    a = alloc.payload["a"]
    for y in results[:cap]:
        ep.update(1 if y == 1 else 0)
        if ep.crossed(a):
            return ep.trials, ep.successes, round(ep.max_log_e, 9), True
    return ep.trials, ep.successes, round(ep.max_log_e, 9), False


def make_confirmation(cand, alloc, result_nodes, params):
    """Confirmation record from the in-order results. A missing (quarantined) result
    counts as Y = 0, and a decision of `confirmed` is only allowed when every
    consumed result is present: repair can therefore never add a confirmation
    (Theorem 2 of the Stage 7 notes)."""
    ys = [r.payload.get("y") if r is not None else None for r in result_nodes]
    n, s, mle, ok = evaluate_confirmation(alloc, ys, params.alpha, params.cap, params.bet_cap)
    if ok and any(r is None for r in result_nodes[:n]):
        ok = False
    edges = [("weight", "Allocation", alloc.key, alloc.digest()), ("for", "Candidate", cand.key, cand.digest())]
    for r in result_nodes[:n]:
        if r is not None:
            edges.append(("evidence", "Result", r.key, r.digest()))
    return Node("Confirmation", cand.key,
                {"n": n, "s": s, "max_log_e": mle, "confirmed": ok, "level": cand.payload["level"]},
                "arbiter", tuple(edges))


# ---------------------------------------------------------------- evidence collection
def _parse_id(s):
    t, k = s.split(":", 1)
    return (t, k)


def discover(fabric):
    """Node ids attested by an intact stored copy (the store key matches the decoded
    id) or by at least two failure domains (anchor-log entries, edge targets). A
    single corrupted log entry or edge cannot invent a phantom record."""
    seen = defaultdict(set)
    intact = set()
    for d, st in fabric.stores.items():
        for sid, b in st.blobs.items():
            try:
                node = Node.decode(b)
            except ValueError:
                seen[sid].add(d)             # the key itself is uncorrupted storage metadata
                continue
            if node.id == sid:
                intact.add(sid)
            seen[sid].add(d)
            for _, tt, tk, _ in node.edges:
                seen[(tt, tk)].add(d)
        for idstr, _, _ in st.anchor_entries():
            try:
                seen[_parse_id(idstr)].add(d)
            except ValueError:
                pass
    ids = {i for i, ds in seen.items() if i in intact or len(ds) >= 2}
    return {i for i in ids if i[0] in TYPE_OWNER}


def build_reverse_index(fabric):
    rev = defaultdict(list)            # target id -> [(domain, digest)]
    for d, st in fabric.stores.items():
        for sid, b in st.blobs.items():
            try:
                node = Node.decode(b)
            except ValueError:
                continue
            if node.id != sid:
                continue
            for _, tt, tk, td in node.edges:
                rev[(tt, tk)].append((d, td))
    return rev


def build_log_index(fabric):
    idx = defaultdict(list)            # id -> [(domain, digest)]
    for d, st in fabric.stores.items():
        for idstr, dg, ok in st.anchor_entries():
            if ok:
                try:
                    idx[_parse_id(idstr)].append((d, dg))
                except ValueError:
                    pass
    return idx


def collect(fabric, nid, cfg, rev, logs):
    owner = TYPE_OWNER[nid[0]]
    copies = {}                         # domain -> Node (decodable, id-consistent)
    items = []                          # (domain, digest, kind) with kind "copy" or "anchor"
    for d, st in fabric.stores.items():
        if not cfg.use_replicas and d != owner:
            continue
        b = st.blobs.get(nid)
        if b is None:
            continue
        try:
            node = Node.decode(b)
        except ValueError:
            continue
        if node.id != nid or node.owner != owner:
            continue
        copies[d] = node
        items.append((d, node.digest(), "copy"))
    if cfg.use_log_anchors:
        items.extend((d, dg, "anchor") for d, dg in logs.get(nid, []))
    if cfg.use_edge_anchors:
        items.extend((d, dg, "anchor") for d, dg in rev.get(nid, []))
    return copies, items


def tally(items, cfg):
    """Votes come from write-time commitments (anchors) only; a copy cannot vouch for
    itself. With domain_votes, each failure domain casts one vote: the majority digest
    among its anchors (abstaining on an internal tie). copy_votes=True turns this into
    plain replica-majority voting, kept as an ablation baseline."""
    voting = [(d, dg) for d, dg, kind in items if kind == "anchor" or cfg.copy_votes]
    if cfg.domain_votes:
        per = defaultdict(Counter)
        for d, dg in voting:
            per[d][dg] += 1
        votes = []
        for d, c in per.items():
            (top, n), *rest = c.most_common()
            if not rest or rest[0][1] < n:
                votes.append(top)
    else:
        votes = [dg for _, dg in voting]
    return Counter(votes), len(votes)


def support(items, digest):
    """Distinct domains holding any evidence (anchor or copy) for this digest."""
    return len({d for d, dg, _ in items if dg == digest})


# ---------------------------------------------------------------- derivations
class Deriver:
    def __init__(self, params, accepted):
        self.p = params
        self.acc = accepted                     # id -> accepted Node (verified/repaired/reconstructed)

    def derive(self, nid):
        t, k = nid
        try:
            if t == "Lease":
                return make_lease(int(k), self.p)
            if t == "Allocation":
                cand = self.acc.get(("Candidate", k))
                if cand is None:
                    return None
                lease = self.acc.get(("Lease", cand.payload["lease"]))
                return make_allocation(cand, lease) if lease is not None else None
            if t == "Key":
                j, kk = k.rsplit(":", 1)
                cand = self.acc.get(("Candidate", j))
                return make_key(cand, int(kk), self.p) if cand is not None else None
        except (KeyError, ValueError, TypeError):
            return None
        return None                             # Candidate, Grant, SlotLease, Result: not derivable


# ---------------------------------------------------------------- the algorithm
def twgr(fabric, params, cfg=None, heal=True):
    """Repair every record. Returns (status: id -> status, accepted: id -> Node)."""
    cfg = cfg or TWGRConfig()
    rev = build_reverse_index(fabric) if cfg.use_edge_anchors else {}
    logs = build_log_index(fabric) if cfg.use_log_anchors else {}
    ids = discover(fabric)
    status, accepted = {}, {}
    der = Deriver(params, accepted)
    for t in TYPE_ORDER:
        for nid in sorted(i for i in ids if i[0] == t):
            if t == "Confirmation":
                continue                       # handled below from verified inputs
            st, node = decide(fabric, nid, cfg, rev, logs, der)
            status[nid] = st
            if node is not None:
                accepted[nid] = node
                if heal and st in (REPAIRED, RECONSTRUCTED):
                    heal_copies(fabric, node)
    # Confirmations: accept a stored copy only if anchored; otherwise re-derive from
    # verified allocation + results (quarantined results count as Y = 0).
    for nid in sorted(i for i in ids if i[0] == "Confirmation"):
        st, node = decide(fabric, nid, cfg, rev, logs, der, derive_fn=lambda n: derive_confirmation(n, accepted, params))
        status[nid] = st
        if node is not None:
            accepted[nid] = node
            if heal and st in (REPAIRED, RECONSTRUCTED):
                heal_copies(fabric, node)
    return status, accepted


def derive_confirmation(nid, accepted, params):
    cand = accepted.get(("Candidate", nid[1]))
    alloc = accepted.get(("Allocation", nid[1]))
    if cand is None or alloc is None:
        return None
    results = []
    k = 1
    while k <= params.cap:
        r = accepted.get(("Result", f"{nid[1]}:{k}"))
        if r is None and ("Result", f"{nid[1]}:{k}") not in accepted and not _known_slot(accepted, nid[1], k):
            break
        results.append(r)
        k += 1
    return make_confirmation(cand, alloc, results, params)


def _known_slot(accepted, j, k):
    return ("SlotLease", f"{j}:{k}") in accepted


def decide(fabric, nid, cfg, rev, logs, der, derive_fn=None):
    copies, items = collect(fabric, nid, cfg, rev, logs)
    if not cfg.quarantine:                       # naive best effort
        owner = TYPE_OWNER[nid[0]]
        node = copies.get(owner) or next(iter(copies.values()), None)
        return (BEST_EFFORT, node) if node is not None else (LOST, None)
    counts, voters = tally(items, cfg)
    derived = None
    if cfg.use_derivation:
        derived = derive_fn(nid) if derive_fn else der.derive(nid)
    if counts:
        best, c = counts.most_common(1)[0]
        anchored = 2 * c > voters and support(items, best) >= cfg.min_support
    else:
        best, anchored = None, False
    if anchored:
        hit = next((n for n in copies.values() if n.digest() == best), None)
        if hit is not None:
            clean = all(n.digest() == best for n in copies.values()) and len(copies) == len(fabric.placement(hit))
            return (VERIFIED if clean else REPAIRED), hit
        if derived is not None and derived.digest() == best:
            return RECONSTRUCTED, derived
        return QUARANTINED, None
    # no anchored majority: a derivation from verified inputs is exact by construction
    if derived is not None:
        dg = derived.digest()
        if copies and all(n.digest() == dg for n in copies.values()) and len(copies) == len(fabric.placement(derived)):
            return VERIFIED, derived           # verified by exact derivation (its anchors may be lost)
        agree = any(n.digest() == dg for n in copies.values())
        return (REPAIRED if agree else RECONSTRUCTED), derived
    return QUARANTINED, None


def heal_copies(fabric, node):
    b = node.encode()
    for d in fabric.placement(node):
        fabric.stores[d].repair_put(node.id, b)


def report(accepted):
    """Final report computed only from accepted records: confirmed levels and b_hat.
    A malformed confirmation (possible only under the best-effort baseline) counts as
    unconfirmed."""
    confirmed = []
    for nid, n in accepted.items():
        if nid[0] == "Confirmation" and n.payload.get("confirmed") is True:
            try:
                confirmed.append((int(n.payload["level"]), n.key))
            except (KeyError, TypeError, ValueError):
                pass
    b_hat = min((lv for lv, _ in confirmed), default=None)
    return {"b_hat": b_hat, "confirmed": sorted(confirmed)}
