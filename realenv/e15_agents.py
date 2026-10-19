"""E15: ten agents on the same stratified AgentDojo scenarios (6 user tasks per suite,
with and without the important_instructions attack: 48 episodes per agent). Resumable;
stops at a deadline so it can be re-launched in chunks.

Run: python3 realenv/e15_agents.py <deadline minutes>
"""

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from realenv.e14_judge import RAW, run  # noqa: E402

AGENTS = ("qwen2.5:0.5b", "llama3.2:1b", "qwen2.5:1.5b", "qwen3:1.7b", "granite3.3:2b", "qwen2.5:3b",
          "llama3.2:3b", "phi4-mini", "qwen2.5:7b", "llama3.1:8b")
PER_SUITE = 6


def out_path(model):
    return RAW / f"e14_episodes_{model.replace(':', '-')}.jsonl"


if __name__ == "__main__":
    deadline = time.time() + 60 * float(sys.argv[1])
    for m in AGENTS:
        if time.time() > deadline:
            break
        run(m, deadline, out_path(m), per_suite=PER_SUITE)
        p = out_path(m)
        n = len(p.read_text().splitlines()) if p.exists() else 0
        print(f"{m}: {n}/48 episodes", flush=True)
