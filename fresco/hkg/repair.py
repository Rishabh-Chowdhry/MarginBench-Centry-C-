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
    authenticate: bool = False      # TWGR-S: origin signatures + derivation dominance (needs a manifest)


@dataclass
class RunParams:
    """What derivations need: the error-budget policy and the run key."""
    eps: float
    lease_size: int
    run_key: bytes
    alpha: float
    cap: int
    bet_cap: float = 0.5
    manifest: dict = None           # published run manifest {run_id, devices: {worker: pubkey}} (TWGR-S)


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


def make_confirmation(cand, alloc, result_nodes, params, robust=False):
    """Confirmation record from the in-order results. A missing (quarantined) result
    counts as Y = 0, and a decision of `confirmed` is only allowed when every
    consumed result is present: repair can therefore never add a confirmation
    (Theorem 2 of the Stage 7 notes)."""
    ys = [r.payload.get("y") if r is not None else None for r in result_nodes]
    n, s, mle, ok = evaluate_confirmation(alloc, ys, params.alpha, params.cap, params.bet_cap)
    if ok and any(r is None for r in result_nodes[:n]):
        ok = False
    if ok and robust and not robust_confirmed(alloc, result_nodes, params):
        ok = False                              # TWGR-S: unsigned crash slots are unknown, not 0
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


# ---------------------------------------------------------------- authenticity (TWGR-S)
SIGNED = ("Candidate", "Result")                    # evidence that originates at a device
DERIVED = ("Lease", "Allocation", "Key", "Confirmation")  # always recomputed, never trusted from storage
MAX_UNSIGNED = 12                                   # unsigned crashes a confirmation may depend on


def admissible(node, accepted, params):
    """'signed' if node carries a valid origin signature, 'unsigned-crash' if it is an
    unsigned crash result (conservative by construction), else None."""
    from fresco.hkg import sign as sg
    man = params.manifest or {}
    devices, run_id = man.get("devices", {}), man.get("run_id")
    p = node.payload
    try:
        if node.type == "Candidate":
            if set(p) != sg.CANDIDATE_KEYS:              # nothing unsigned may ride along
                return None
            pub = devices.get(p.get("worker"))
            return "signed" if pub and sg.verify(pub, p.get("sig"), sg.request_msg(run_id, p)) else None
        if node.type == "Result":
            if p.get("sig") is None:
                return "unsigned-crash" if p == {"crashed": True} else None
            if set(p) not in sg.RESULT_KEYS:
                return None
            j, k = node.key.rsplit(":", 1)
            cand = accepted.get(("Candidate", j))
            pub = devices.get(p.get("worker"))
            if cand is None or pub is None or p.get("worker") != cand.payload.get("worker"):
                return None
            outcome = "crashed" if p.get("crashed") else p.get("y")
            if outcome not in (0, 1, "crashed"):
                return None
            msg = sg.result_msg(run_id, j, int(k), outcome, sg.request_hash(cand.payload),
                                prf_key(params.run_key, j, int(k)))
            return "signed" if sg.verify(pub, p.get("sig"), msg) else None
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _schema_edges(node):
    """The edge structure of a signed record is fixed by its type and id: relation name
    and target id are rebuilt; only the target digest is taken from the copy."""
    if node.type == "Result":
        j = node.key.rsplit(":", 1)[0]
        return [("for", "Candidate", j), ("key", "Key", node.key), ("lease", "SlotLease", node.key)]
    if node.type == "Candidate":
        return [("funded_by", "Lease", str(node.payload.get("lease")))]
    return []


def normalise_edges(node, accepted, anchored=None):
    """Edges in schema order; each digest from the accepted target, else the target's
    anchored-majority digest, else the copy's, else the edge is omitted (an optional
    edge, or an unrecoverable target). Edges never affect signed or derived content."""
    stored = {tt: td for _, tt, _, td in node.edges}
    edges = []
    for rel, tt, tk in _schema_edges(node):
        if (tt, tk) in accepted:
            td = accepted[(tt, tk)].digest()
        else:
            td = (anchored((tt, tk)) if anchored else None) or stored.get(tt)
        if td is not None:
            edges.append((rel, tt, tk, td))
    return Node(node.type, node.key, node.payload, node.owner, tuple(edges))


def _wellformed(digest):
    return isinstance(digest, str) and len(digest) == 32 and set(digest) <= set("0123456789abcdef")


def decide_signed(fabric, nid, copies, accepted, params, anchored=None, edge_support=None):
    """Authenticity comes from the origin signature, not from votes: an adversary holding
    any number of coordinator domains cannot make a forged value admissible. Two
    distinct signed values for one id mean the device equivocated: quarantine."""
    by_payload = defaultdict(list)                    # signed content -> normalised admissible copies
    kind = {}
    for n in copies.values():
        a = admissible(n, accepted, params)
        if a is not None:
            key = canon(n.payload)
            kind[key] = a
            by_payload[key].append(normalise_edges(n, accepted, anchored))
    signed = [k for k, a in kind.items() if a == "signed"]
    if len(signed) > 1:
        return QUARANTINED, None
    chosen = signed[0] if signed else next((k for k, a in kind.items() if a == "unsigned-crash"), None)
    if chosen is None:
        return QUARANTINED, None
    # edges are not signed: they are rebuilt from accepted neighbours; any edge whose
    # target is unverifiable keeps the value most copies agree on
    counts = Counter(n.encode() for n in by_payload[chosen])
    if len(counts) > 1 and edge_support:              # copies disagree on an unverifiable edge:
        def score(b):                                 # well-formed and anchor-backed digests first
            n = Node.decode(b)
            return (sum(_wellformed(td) for _, _, _, td in n.edges),
                    sum(edge_support((tt, tk), td) for _, tt, tk, td in n.edges), counts[b])
        pick = max(counts, key=score)
    else:
        pick = counts.most_common(1)[0][0]
    pick = Node.decode(pick)
    clean = all(n.encode() == pick.encode() for n in copies.values()) and len(copies) == len(fabric.placement(pick))
    return (VERIFIED if clean else REPAIRED), pick


def decide_derived(fabric, nid, copies, derived):
    """Derivation dominance: a derivable record is exactly its derivation from accepted
    inputs; stored copies and votes can never override it."""
    if derived is None:
        return QUARANTINED, None
    dg = derived.digest()
    if copies and all(n.digest() == dg for n in copies.values()) and len(copies) == len(fabric.placement(derived)):
        return VERIFIED, derived
    agree = any(n.digest() == dg for n in copies.values())
    return (REPAIRED if agree else RECONSTRUCTED), derived


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
                if cand is None or cand.payload["lease"] in getattr(self, "overspent", ()):
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
        if cfg.authenticate and t == "Allocation":
            der.overspent = overspent_leases(accepted, params)
        for nid in sorted(i for i in ids if i[0] == t):
            if t == "Confirmation":
                continue                       # handled below from verified inputs
            st, node = decide(fabric, nid, cfg, rev, logs, der, params=params)
            status[nid] = st
            if node is not None:
                accepted[nid] = node
                if heal and st in (REPAIRED, RECONSTRUCTED):
                    heal_copies(fabric, node)
    # Confirmations: accept a stored copy only if anchored; otherwise re-derive from
    # verified allocation + results (quarantined results count as Y = 0).
    for nid in sorted(i for i in ids if i[0] == "Confirmation"):
        st, node = decide(fabric, nid, cfg, rev, logs, der, params=params,
                          derive_fn=lambda n: derive_confirmation(n, accepted, params, robust=True))
        status[nid] = st
        if node is not None:
            accepted[nid] = node
            if heal and st in (REPAIRED, RECONSTRUCTED):
                heal_copies(fabric, node)
    return status, accepted


def overspent_leases(accepted, params):
    """Leases funding more distinct signed requests than their size (only possible if a
    compromised Treasurer granted one lease twice): all their candidates become
    unconfirmable, so sum a_j <= eps holds over what can be confirmed."""
    from fresco.hkg.sign import request_hash
    reqs = defaultdict(set)
    for (t, _), n in accepted.items():
        if t == "Candidate":
            reqs[n.payload.get("lease")].add(request_hash(n.payload))
    return {lease for lease, r in reqs.items() if len(r) > params.lease_size}


def robust_confirmed(alloc, results, params):
    """Confirmed for every assignment of the unsigned crash slots to {0, 1}. The true
    sequence is one of these assignments, so a robust confirmation was also made by the
    original run, whatever an adversary substituted (the e-process is not monotone in
    individual outcomes, so setting them to 0 is not enough)."""
    import itertools
    free = [i for i, r in enumerate(results[:params.cap])
            if r is not None and r.payload.get("crashed") and r.payload.get("sig") is None]
    if len(free) > MAX_UNSIGNED:
        return False
    base = [r.payload.get("y") if r is not None else None for r in results]
    for bits in itertools.product((0, 1), repeat=len(free)):
        ys = list(base)
        for i, b in zip(free, bits):
            ys[i] = b
        if not evaluate_confirmation(alloc, ys, params.alpha, params.cap, params.bet_cap)[3]:
            return False
    return True


def derive_confirmation(nid, accepted, params, robust=False):
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
    return make_confirmation(cand, alloc, results, params, robust=robust)


def _known_slot(accepted, j, k):
    return ("SlotLease", f"{j}:{k}") in accepted


def decide(fabric, nid, cfg, rev, logs, der, derive_fn=None, params=None):
    copies, items = collect(fabric, nid, cfg, rev, logs)
    if cfg.authenticate:
        if nid[0] in SIGNED:
            def anchored(tid):
                d = der.derive(tid)                   # a derivable target's digest is exact
                if d is not None:
                    return d.digest()
                items = collect(fabric, tid, cfg, rev, logs)[1]
                counts, voters = tally(items, cfg)
                if counts:
                    best, c = counts.most_common(1)[0]
                    if 2 * c > voters:
                        return best
                return None
            def edge_support(tid, digest):
                return support(collect(fabric, tid, cfg, rev, logs)[1], digest)
            return decide_signed(fabric, nid, copies, der.acc, params, anchored, edge_support)
        if nid[0] in DERIVED:
            return decide_derived(fabric, nid, copies, derive_fn(nid) if derive_fn else der.derive(nid))
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
