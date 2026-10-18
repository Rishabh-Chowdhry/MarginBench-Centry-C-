"""E13: real agent episodes in AgentDojo's simulated tool environments, driven by a
free local LLM (Ollama). The study is descriptive: per-episode outcome (AgentDojo's
own security and utility checks) and latency, from which experiments report timeout
rates by outcome and the inflation a fresh-key retry would cause.

Episodes run in a fixed order over (suite, user task, injection task, seed), and
results are appended, so a run can be resumed or stopped at a deadline without
biasing which episodes were run (the order is fixed before execution, and seeds
rotate fastest).

Run: python3 realenv/e13_agentdojo.py <model> <deadline minutes>
"""

import json
import pathlib
import sys
import time
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from realenv.agentdojo_episode import run_episode  # noqa: E402

OUT = ROOT / "results" / "raw" / "e13_agentdojo.jsonl"
PAIRS = [("banking", f"user_task_{u}", f"injection_task_{i}") for u, i in
         ((0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5))] + \
        [("slack", f"user_task_{u}", f"injection_task_{i}") for u, i in
         ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 1))]
SEEDS = range(1, 6)
ATTACK = "important_instructions"


def main():
    model, deadline = sys.argv[1], time.time() + 60 * float(sys.argv[2])
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            r = json.loads(line)
            done.add((r["suite"], r["user_task"], r["injection_task"], r["seed"], r["model"]))
    order = [(p, s) for s in SEEDS for p in PAIRS]
    for (suite, ut, it), seed in order:
        if (suite, ut, it, seed, model) in done:
            continue
        if time.time() > deadline:
            print("deadline reached", flush=True)
            break
        try:
            r = run_episode(suite, ut, it, ATTACK, model, seed)
        except Exception as e:
            r = {"suite": suite, "user_task": ut, "injection_task": it, "attack": ATTACK, "model": model,
                 "seed": seed, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
        with open(OUT, "a") as f:
            f.write(json.dumps(r) + "\n")
        print(json.dumps({k: r.get(k) for k in ("suite", "user_task", "seed", "violation", "utility", "latency_s",
                                                "error")}), flush=True)


if __name__ == "__main__":
    main()
