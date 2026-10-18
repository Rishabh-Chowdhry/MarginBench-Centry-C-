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

from experiments.common import run_jobs_streaming  # noqa: E402
from experiments.e10_corruption import PARAMS, SCENARIOS, VARIANTS  # noqa: E402
from fresco.hkg.corrupt import tamper_node  # noqa: E402
from fresco.hkg.graph import DOMAINS, Node, canon, nid_str, sha  # noqa: E402
from fresco.hkg.repair import QUARANTINED, build_log_index, build_reverse_index, report, twgr  # noqa: E402
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


ATTACKS = (("tamper-result", 8), ("tamper-confirmation", 6), ("suppress-result", 6), ("inflate-lease", 3),
           ("retarget-candidate", 4))
EVAL = ("TWGR", "TWGR-S", "replica-majority")


def targets(truth, attack, rng, n):
    def pl(i):
        return Node.decode(truth[i]).payload
    pool = {"tamper-result": lambda i: i[0] == "Result" and pl(i).get("y") == 0,
            "tamper-confirmation": lambda i: i[0] == "Confirmation" and not pl(i)["confirmed"],
            "suppress-result": lambda i: i[0] == "Result" and pl(i).get("y") == 1,
            "inflate-lease": lambda i: i[0] == "Lease",
            "retarget-candidate": lambda i: i[0] == "Candidate" and pl(i)["level"] > 1}[attack]
    ids = sorted(i for i in truth if pool(i))
    return [ids[int(t)] for t in rng.choice(len(ids), size=min(n, len(ids)), replace=False)]


def forged(node, attack):
    if attack == "suppress-result":                 # a signed outcome replaced by an unsigned crash
        return Node(node.type, node.key, {"crashed": True}, node.owner, node.edges)
    return tamper_node(node)                        # format-valid rewrite (signatures, if any, now stale)


def one(cfg):
    rng = np.random.default_rng(cfg["seed"])
    q = Quintet(SCENARIOS["S1-dense"], PARAMS, QuintetConfig(workers=4, budget=1500, crash=0.02),
                np.random.default_rng(cfg["seed"]))
    q.run()
    truth = q.fabric.truth
    true_conf = {k for _, k in q.truth_report()["confirmed"]}
    rows = []
    for attack, n in ATTACKS:
        for nid in targets(truth, attack, rng, n):
            anchors = anchor_domains(q.fabric, nid)
            bad = forged(Node.decode(truth[nid]), attack)
            for k in range(1, 6):
                B = [str(d) for d in rng.choice(DOMAINS, size=k, replace=False)]
                b = len(set(B) & anchors)
                for name in EVAL:
                    fab = copy.deepcopy(q.fabric)
                    control(fab, nid, bad, B)
                    status, acc = twgr(fab, q.p, VARIANTS[name], heal=False)
                    got = acc.get(nid)
                    wrong = int(got is not None and got.payload != Node.decode(truth[nid]).payload)
                    added = {kk for _, kk in report(acc)["confirmed"]} - true_conf
                    rows.append({"attack": attack, "type": nid[0], "k": k, "m": len(anchors), "b": b, "variant": name,
                                 "wrong": wrong, "correct": int(got is not None and got.encode() == truth[nid]),
                                 "links_differ": int(got is not None and not wrong and got.encode() != truth[nid]),
                                 "quarantined": int(status.get(nid) == QUARANTINED),
                                 "conservative": int(wrong and got.payload == {"crashed": True}),
                                 "added_conf": len(added), "majority": int(2 * b > len(anchors))})
    return {"rows": rows}


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    run_jobs_streaming("e11_adversary", [(one, {"seed": r}, {"seed": 20_000 + r}) for r in range(runs)])
