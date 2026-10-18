"""On-disk storage faults for the QUINTET coordinators' JSONL data files (run while
the coordinators are stopped). Kinds per line: bitflip (one byte of the line),
truncate, delete, tamper (format-valid: the stored record is decoded, tampered with
fresco.hkg.corrupt.tamper_node and re-encoded; an anchor-log line gets a random digest).
"""

import base64
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fresco.hkg.corrupt import tamper_node  # noqa: E402
from fresco.hkg.graph import Node, sha  # noqa: E402

KINDS = ("bitflip", "truncate", "delete", "tamper")


def corrupt_line(line, kind, rng):
    if kind == "delete":
        return None
    if kind == "truncate":
        return line[: int(rng.integers(len(line)))] if line else line
    if kind == "bitflip":
        b = bytearray(line.encode())
        i = int(rng.integers(len(b)))
        b[i] ^= 1 << int(rng.integers(7))
        return b.decode(errors="replace")
    try:
        d = json.loads(line)
        if "log" in d:
            e = json.loads(d["log"])
            e["d"] = sha(str(rng.random()).encode())
            d["log"] = json.dumps(e)
        else:
            n = tamper_node(Node.decode(base64.b64decode(d["b"])))
            d["b"] = base64.b64encode(n.encode()).decode()
        return json.dumps(d)
    except Exception:
        return corrupt_line(line, "bitflip", rng)


def corrupt_file(path, rho, rng, kinds=KINDS):
    lines = pathlib.Path(path).read_text().splitlines()
    out, n = [], 0
    for ln in lines:
        if rng.random() < rho:
            n += 1
            ln = corrupt_line(ln, kinds[int(rng.integers(len(kinds)))], rng)
            if ln is None:
                continue
        out.append(ln)
    pathlib.Path(path).write_text("\n".join(out) + "\n")
    return {"lines": len(lines), "corrupted": n}
