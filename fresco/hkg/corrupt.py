"""Storage corruption injector for the five domain stores.

Each stored item (node copy or anchor-log entry) is corrupted independently with
probability rho. Kinds:
  bitflip  flip one random bit
  truncate cut the bytes at a random point
  delete   remove the item
  tamper   format-valid semantic change that a parser accepts: a result's y set to
           1, a confirmation marked confirmed, a budget or allocation inflated, a
           candidate's level changed, an anchor digest replaced
`coordinated` additionally applies the *same* tamper to the same record in the
given number of domains (the worst case the quorum bound is about).
"""

import json

from fresco.hkg.graph import Node, sha

KINDS = ("bitflip", "truncate", "delete", "tamper")


def tamper_node(node):
    p = dict(node.payload)
    t = node.type
    if t == "Result":
        p.pop("crashed", None)
        p["y"] = 1
    elif t == "Confirmation":
        p["confirmed"] = True
    elif t in ("Allocation",):
        p["a"] = p.get("a", 0.0) * 10
    elif t == "Lease":
        p["amount"] = p.get("amount", 0.0) * 10
    elif t == "Candidate":
        p["level"] = max(1, int(p.get("level", 1)) - 1)
    elif t == "Frontier":
        p["b_hat"] = max(1, int(p.get("b_hat", 1)) - 1)
    else:
        p["_t"] = 1
    if p == node.payload:
        p["_t"] = 1
    return Node(node.type, node.key, p, node.owner, node.edges)


def corrupt_bytes(b, kind, rng):
    if kind == "bitflip" and b:
        i = int(rng.integers(len(b)))
        arr = bytearray(b)
        arr[i] ^= 1 << int(rng.integers(8))
        return bytes(arr)
    if kind == "truncate" and b:
        return b[: int(rng.integers(len(b)))]
    if kind == "tamper":
        try:
            return tamper_node(Node.decode(b)).encode()
        except ValueError:
            return corrupt_bytes(b, "bitflip", rng)
    return b


def corrupt_fabric(fabric, rho, rng, kinds=KINDS, only_types=None):
    """Independent corruption of every stored item. Returns a dict of counts."""
    n = {"items": 0, "corrupted": 0}
    for st in fabric.stores.values():
        for nid in list(st.blobs):
            if only_types and nid[0] not in only_types:
                continue
            n["items"] += 1
            if rng.random() < rho:
                n["corrupted"] += 1
                kind = kinds[int(rng.integers(len(kinds)))]
                if kind == "delete":
                    del st.blobs[nid]
                else:
                    st.blobs[nid] = corrupt_bytes(st.blobs[nid], kind, rng)
        for i, raw in enumerate(list(st.log)):
            n["items"] += 1
            if rng.random() < rho:
                n["corrupted"] += 1
                kind = kinds[int(rng.integers(len(kinds)))]
                if kind == "delete":
                    st.log[i] = ""
                elif kind == "tamper":
                    try:
                        e = json.loads(raw)
                        e["d"] = sha(str(rng.random()).encode())
                        st.log[i] = json.dumps(e)
                    except ValueError:
                        st.log[i] = raw[: len(raw) // 2]
                else:
                    st.log[i] = corrupt_bytes(raw.encode(), kind, rng).decode(errors="replace")
    return n


def coordinated_tamper(fabric, nid, domains):
    """Apply the identical format-valid tamper to `nid` in the given domains (copies,
    plus re-anchoring in those domains' logs): an adversary controlling those domains."""
    for d in domains:
        st = fabric.stores[d]
        if nid in st.blobs:
            try:
                bad = tamper_node(Node.decode(st.blobs[nid]))
            except ValueError:
                continue
            st.blobs[nid] = bad.encode()
            st.append_anchor(nid, bad.digest())
