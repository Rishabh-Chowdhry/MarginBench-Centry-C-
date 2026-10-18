"""E11 (preregistered in docs/stage7_quintet_hkg_twgr.md §6): a coordinated adversary
that fully controls k of the five domains and writes one consistent wrong value of a
target record everywhere it can: the stored copy, every anchor-log entry (re-chaining
the log so its hash chain still verifies), and the digest in every edge pointing at the
target from records it stores. Targets are Results with y = 0 (rewritten to y = 1) and
unconfirmed Confirmations (rewritten to confirmed).

Theorem 1 predicts wrong acceptance is impossible while the compromised anchor domains
are not a strict majority of the domains holding anchors for the target; the remark
says it becomes possible beyond that. Replica-majority voting is run on the same
attacks for comparison.

Run: python3 -I experiments/e11_adversary.py [runs]   (default 20)
"""

import copy
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from experiments.common import run_jobs  # noqa: E402
from experiments.e10_corruption import PARAMS, SCENARIOS, VARIANTS  # noqa: E402
from fresco.hkg.corrupt import tamper_node  # noqa: E402
from fresco.hkg.graph import DOMAINS, Node, canon, nid_str, sha  # noqa: E402
from fresco.hkg.repair import QUARANTINED, build_log_index, build_reverse_index, twgr  # noqa: E402
from fresco.quintet.cluster import Quintet, QuintetConfig  # noqa: E402

TARGETS = 12


def rechain(st, start):
    prev = json.loads(st.log[start - 1])["c"] if start else "genesis"
    for i in range(start, len(st.log)):
        e = json.loads(st.log[i])
        e["c"] = sha(canon([prev, e["id"], e["d"]]))
        prev = e["c"]
        st.log[i] = json.dumps(e)


def control(fab, nid, bad, domains):
    sid, bd = nid_str(nid), bad.digest()
    for d in domains:
        st = fab.stores[d]
        if nid in st.blobs or d in fab.placement(bad):
            st.blobs[nid] = bad.encode()
        first = None
        for i, raw in enumerate(st.log):
            e = json.loads(raw)
            if e["id"] == sid:
                e["d"] = bd
                st.log[i] = json.dumps(e)
                first = i if first is None else first
        if first is not None:
            rechain(st, first)
        for oid, b in list(st.blobs.items()):
            if oid == nid:
                continue
            n = Node.decode(b)
            if any((tt, tk) == nid for _, tt, tk, _ in n.edges):
                edges = tuple((r, tt, tk, bd if (tt, tk) == nid else td) for r, tt, tk, td in n.edges)
                st.blobs[oid] = Node(n.type, n.key, n.payload, n.owner, edges).encode()


def anchor_domains(fab, nid):
    logs, rev = build_log_index(fab), build_reverse_index(fab)
    return {d for d, _ in logs.get(nid, [])} | {d for d, _ in rev.get(nid, [])}


def one(cfg):
    rng = np.random.default_rng(cfg["seed"])
    q = Quintet(SCENARIOS["S1-dense"], PARAMS, QuintetConfig(workers=4, budget=1500, crash=0.02),
                np.random.default_rng(cfg["seed"]))
    q.run()
    truth = q.fabric.truth
    res = [i for i in truth if i[0] == "Result" and Node.decode(truth[i]).payload.get("y") == 0]
    conf = [i for i in truth if i[0] == "Confirmation" and not Node.decode(truth[i]).payload["confirmed"]]
    picks = [res[int(t)] for t in rng.choice(len(res), size=min(TARGETS, len(res)), replace=False)]
    picks += [conf[int(t)] for t in rng.choice(len(conf), size=min(TARGETS // 2, len(conf)), replace=False)]
    rows = []
    for nid in picks:
        anchors = anchor_domains(q.fabric, nid)
        bad = tamper_node(Node.decode(truth[nid]))
        for k in range(1, 6):
            B = [str(d) for d in rng.choice(DOMAINS, size=k, replace=False)]
            b = len(set(B) & anchors)
            for name in ("TWGR", "replica-majority"):
                fab = copy.deepcopy(q.fabric)
                control(fab, nid, bad, B)
                status, acc = twgr(fab, PARAMS, VARIANTS[name], heal=False)
                got = acc.get(nid)
                rows.append({"type": nid[0], "k": k, "m": len(anchors), "b": b, "variant": name,
                             "placement_hit": len(set(B) & set(q.fabric.placement(bad))),
                             "wrong": int(got is not None and got.encode() != truth[nid]),
                             "correct": int(got is not None and got.encode() == truth[nid]),
                             "quarantined": int(status.get(nid) == QUARANTINED),
                             "majority": int(2 * b > len(anchors))})
    return {"rows": rows}


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    run_jobs("e11_adversary", [(one, {"seed": r}, {"seed": 20_000 + r}) for r in range(runs)])
