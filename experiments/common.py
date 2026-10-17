"""Shared experiment runner: parallel execution, JSONL results with manifests."""

import json
import multiprocessing as mp
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fresco.manifest import config_hash, git_revision  # noqa: E402

RAW = ROOT / "results" / "raw"


def _run(job):
    fn, meta, cfg = job
    t0 = time.time()
    out = fn(cfg)
    out = {k: v for k, v in out.items() if k not in ("certificates",)} | (
        {"certificates": out["certificates"]} if "certificates" in out else {})
    return {**meta, "config_hash": config_hash(cfg), "wall_s": round(time.time() - t0, 3), **out}


def run_jobs(name, jobs, processes=None):
    """jobs: list of (callable, meta dict, config). Writes results/raw/<name>.jsonl."""
    RAW.mkdir(parents=True, exist_ok=True)
    rev = git_revision()
    t0 = time.time()
    with mp.Pool(processes or mp.cpu_count()) as pool:
        rows = pool.map(_run, jobs, chunksize=1)
    path = RAW / f"{name}.jsonl"
    with open(path, "w") as f:
        f.write(json.dumps({"_manifest": {"experiment": name, "code_revision": rev, "jobs": len(jobs),
                                          "python": sys.version.split()[0],
                                          "elapsed_s": round(time.time() - t0, 1)}}) + "\n")
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"{name}: {len(rows)} runs in {time.time() - t0:.0f}s -> {path.relative_to(ROOT)}")
    return rows


def load(name):
    rows = []
    with open(RAW / f"{name}.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if "_manifest" not in d:
                rows.append(d)
    return rows
