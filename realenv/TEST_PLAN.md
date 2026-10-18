# QUINTET real-environment SQA test plan (E12)

This plan was written and committed before any test case was run. Results are in `realenv/RESULTS.md` and `results/raw/e12_sqa.jsonl`.

## Environment (all free and open source)
| Component | What it is |
|---|---|
| Devices | Docker containers built from `quintet-device:1` (python:3.12-slim + numpy), created by `realenv/build_image.sh` |
| Coordinators | 5 containers `q-registrar`, `q-treasurer`, `q-recorder`, `q-arbiter`, `q-archivist`, each with its own bind-mounted data directory, on a private bridge network `qnet` |
| Workers | N worker containers, the simulated executor devices, each limited to `--cpus 0.5 --memory 192m` |
| Network fault injection | Toxiproxy (Shopify, MIT) runs in its own container. Every worker→coordinator connection goes through a Toxiproxy proxy, and toxics (latency, jitter, timeout, reset_peer, bandwidth limit) are added through its HTTP API |
| Process and host faults | `docker kill` (crash), `docker pause` / `unpause` (freeze, SIGSTOP), `docker network disconnect` / `connect` (partition) |
| Storage faults | `realenv/disk_corrupt.py` edits the coordinators' on-disk JSONL files while they are stopped. Edits are bit flips, truncation, line deletion, format-valid tampers (a Result's y set to 1, a Confirmation set to confirmed, inflated budgets) and anchor rewrites |
| Harness | `realenv/sqa_campaign.py`, run on the host, which talks to the published coordinator ports and to the Docker CLI |

## Invariants checked after every test case
The harness pulls every domain's dump and runs TWGR locally without healing. It also triggers the Archivist's `/scan`, which does heal.

| ID | Invariant |
|---|---|
| I1 write-once / exactly-once | No record has two different decodable, id-consistent values across domains (before storage faults); at most one Result per slot (j, k) |
| I2 budget (R5) | Σ of accepted Allocation weights ≤ ε, and each lease funds at most `lease_size` allocations |
| I3 no stuck slots (R4) | Every SlotLease has a Result once the cluster is quiescent (expired slots become crash results) |
| I4 verifiable confirmations (R6) | Every stored Confirmation equals its re-derivation from the accepted Allocation and Results |
| I5 replication | After the replication queues drain, every record is present at all 3 placement domains |
| I6 frontier | The reported b̂ equals the minimum confirmed level |

## Test cases
| TC | Fault | Pass criterion |
|---|---|---|
| TC1 | None (baseline). 6 workers, S1-dense | I1–I6 hold. All records VERIFIED. b̂ = k* = 3 |
| TC2 | Latency 150 ms ± 100 ms on every worker link | I1–I6 hold |
| TC3 | `timeout` and `reset_peer` toxics with toxicity 0.15 on worker→Recorder and worker→Registrar | I1–I6 hold. Late or duplicated results are fenced or idempotent, with no conflicts |
| TC4 | `docker kill q-recorder` mid-run, restarted after 10 s | I1–I6 hold. Replication backlog drains to 0. Workers finish |
| TC5 | `docker pause q-arbiter` for 15 s mid-run | I1–I6 hold |
| TC6 | `docker network disconnect qnet q-treasurer` for 15 s mid-run | I1–I6 hold |
| TC7 | `docker kill` of 2 of 6 workers mid-run | I1–I6 hold. Their open slots expire into crash results (I3) |
| TC8 | On-disk corruption at ρ ∈ {0.05, 0.2, 0.4} after a TC1-style run; all coordinators restarted; Archivist scan | Against the golden pre-corruption graph: **0 wrong accepted non-confirmation records, 0 added confirmations**. Recovery ≥ 0.99 at ρ = 0.05. A second scan after healing finds no REPAIRED records |
| TC9 | Whole data directories of 2 coordinators deleted (disk loss); restart; scan | 0 wrong records, 0 added confirmations |
| TC10 | Consistent adversarial rewrite of one Result in k = 1, 2 domains (files and logs re-chained) | For the minority adversary: the record is accepted correctly or quarantined, never wrong |

*Clarification added after run 3, before run 4:* "minority" is judged per target. It means the compromised domains are at most half of the domains holding anchors for that target (2b ≤ m, the condition of Theorem 1). With k = 2, some targets have m = 3, so the adversary is a majority there, and Theorem 1 predicts that a wrong value can be accepted. The harness now computes b and m for every target.
| TC11 | Validity: boundary-null scenario, 5 independent cluster runs × 6 workers | 0 false confirmations is expected; the bound is P(any) ≤ ε = 0.05 per run. This test is descriptive, because 5 runs cannot estimate a 5% rate |
| TC12 | Resume after the TC4 and TC8 faults: run workers again on the repaired cluster | No write-once conflicts (no id reuse after restart). I1–I6 hold |

## Real agents (E13)
AgentDojo v1.2.1 simulated tool environments (banking, slack, travel, workspace), driven by a free local LLM (qwen2.5 via Ollama in Docker). The study measures per-episode latency and violation outcome, plus timeout rates by outcome. It is descriptive, with no pass criterion.

*Clarification added after run 7, before run 8:* TC12 checks I1, I4 and I5 on the records written after the repair. Records that TWGR quarantined keep their unverifiable copies by design, because repair never overwrites what it cannot verify. Confirmations accepted on their anchors whose inputs were quarantined cannot be re-derived either, and Theorem 2 covers them through its case (a). I2 and I3 remain global, and the criterion also requires no 5xx server errors seen by workers.

*Revision after the majority-adversary loophole report (before run 9):* evidence is now signed by the executor devices, and the coordinators and the harness use TWGR-S. TC10 is extended to adversaries controlling k = 1, …, 5 domains, rewriting both Results (0 → 1) and Confirmations (unconfirmed → confirmed). New pass criterion for every k: **no wrong accepted record and no added confirmation**. Quarantine (lost evidence) is allowed. This holds even when the adversary holds a majority, or all five, of the domains.

*Clarification after run 9, before run 10:* in TC10, a target counts as **wrong** when its accepted content (signed or derived payload) differs from the original. A target whose content is right, but whose evidence links omit a record the adversary destroyed, is reported separately as "content right, links missing". Added confirmations remain a pass criterion of their own.

