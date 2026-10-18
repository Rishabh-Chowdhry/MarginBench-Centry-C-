"""E13b: replay determinism. Re-runs the first episodes of E13 with identical
(task pair, attack, model, seed) and compares AgentDojo outcomes."""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from realenv.agentdojo_episode import run_episode  # noqa: E402

SRC = ROOT / "results" / "raw" / "e13_agentdojo.jsonl"
OUT = ROOT / "results" / "raw" / "e13_replay.jsonl"

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    orig = [json.loads(x) for x in SRC.read_text().splitlines()][:n]
    with open(OUT, "w") as f:
        for o in orig:
            r = run_episode(o["suite"], o["user_task"], o["injection_task"], o["attack"], o["model"], o["seed"])
            r["same_outcome"] = (r["violation"], r["utility"]) == (o["violation"], o["utility"])
            f.write(json.dumps(r) + "\n")
            print(json.dumps({k: r[k] for k in ("suite", "user_task", "seed", "utility", "same_outcome")}), flush=True)
