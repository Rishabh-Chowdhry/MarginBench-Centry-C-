# QUINTET real-environment SQA campaign (E12): results

**Setup and sources.** The test plan, with pass criteria fixed before execution, is in `TEST_PLAN.md`. The campaign ran on:
- one 4-core cloud VM;
- Docker 28 with private bridge networking;
- Toxiproxy 2.x for network faults;
- 5 coordinator containers and 6 worker containers, each worker limited to 0.5 CPU and 192 MB.

**Data files and how to regenerate them:**
- Final run: `results/raw/e12_sqa.jsonl`.
- Earlier failing runs, kept as defect evidence: `results/raw/e12_sqa_run*_*.jsonl`.
- Tables are regenerated with `python3 -I analysis/stage7_figures.py` and written to `results/processed/stage7_summary.md`.

## Final run (run 8; code after fixes D1–D7)
**19 of 21 test cases passed.** Across all storage-fault cases, TWGR accepted **no wrong record and added no confirmation**.

| TC | Fault | Outcome | Verdict |
|---|---|---|---|
| TC1 | none | All invariants hold; 2,254 records all VERIFIED. **b̂ = 4, but k* = 3**: a power miss at this budget (724 episodes), not a correctness failure. Across runs 2–8, TC1 found k* in 6 of 7 runs | FAIL (criterion b̂ = k*) |
| TC2 | latency 150 ± 100 ms on every link | Invariants hold; all VERIFIED | PASS |
| TC3 | timeouts and connection resets (toxicity 0.15) | Invariants hold. 131 slots whose result never arrived expired into crash results (R4); no duplicates, no conflicts | PASS |
| TC4 | Recorder killed mid-run, restarted after 10 s | Invariants hold; all VERIFIED; replication caught up | PASS |
| TC5 | Arbiter frozen for 15 s | Invariants hold | PASS |
| TC6 | Treasurer partitioned for 15 s | Invariants hold. Registrations failed with 503 during the partition; 127 crash results | PASS |
| TC7 | 2 of 6 workers killed | Invariants hold; their open slots expired into crash results | PASS |
| TC8 | on-disk corruption ρ = 0.05 | recovery 0.9996, 0 wrong, 0 added confirmations | PASS |
| TC8 | on-disk corruption ρ = 0.2 | recovery 0.9929, 0 wrong, 0 added confirmations | PASS |
| TC8 | on-disk corruption ρ = 0.4 | recovery 0.9374, 0 wrong, 0 added confirmations. The second scan recovered 1 more record (see note) | FAIL (criterion "second scan finds nothing to repair") |
| TC9 | data of Registrar and Archivist erased | recovery 1.0000, 0 wrong | PASS |
| TC9 | data of Recorder and Arbiter erased | recovery 0.9600, 0 wrong | PASS |
| TC10 | adversary in k = 1 domain | 10/10 targets correct | PASS |
| TC10 | adversary in k = 2 domains | 0 wrong among the 8 targets where the adversary was a minority of the anchor domains. The 2 wrong acceptances were both on targets where it held a majority, which Theorem 1 says no voting scheme can resist | PASS |
| TC11 | boundary null, 5 independent runs | 0 false confirmations in 5 runs (≈ 900 episodes each) | PASS |
| TC12 | resume work after the ρ = 0.2 repair | 760 new or changed records: 0 conflicts, 0 confirmation mismatches, 0 under-replicated, 0 server errors | PASS |

**Note on TC8 at ρ = 0.4.** The record was QUARANTINED by the first scan and REPAIRED by the second. In between, a coordinator that had been healed re-offered one of its anchor-verified copies (its post-recovery resync), which gave TWGR the evidence it lacked. Repair improved monotonically, as it should, but the preregistered criterion "the second scan finds nothing to repair" did not hold. Making the Archivist wait for post-recovery resyncs before returning would fix this; it is not done.

## Defects found by the campaign
Every failing run was kept. Each defect has a regression test in `tests/test_quintet_service.py`.

| ID | Found in | Defect | Severity | Fix |
|---|---|---|---|---|
| D1 | run 1, TC8 | A bit flip inside a stored record id crashed a coordinator's restart while it rebuilt its slot counters | availability | Ids are parsed defensively |
| D2 | run 2, TC8 | A Recorder that lost a Result locally expired that slot after restart and **anchored a fabricated crash result** | **integrity** | Before writing, check the Archivist's anchors and the witnesses; postpone if unknown |
| D3 | run 2 (analysis) | Restart resync re-offered any decodable local copy *with a receipt anchor*, so a tampered copy could gain a vote | **integrity (latent)** | Re-offer only copies verified against the domain's own anchors, without receipts |
| D4 | run 3, TC12 | A coordinator restarted on a damaged store acted on unverified local data (the Arbiter re-decided a lost Confirmation) | **integrity** | *Repair before serve*: self-check on restart; refuse role operations until a TWGR scan has healed the store |
| D5 | run 4, TC12 | Id counters ignored surviving neighbouring records, so an index whose SlotLease was lost was reused | integrity (write-once) | Counters cover every record type keyed by the id |
| D6 | run 5, TC12 | A quarantined, still-corrupted Result was served to the Arbiter, which failed on it; that control message then blocked all replication behind it | **integrity + liveness** | Serve and use only anchor-verified local copies; separate per-peer data and control queues; bound retries of control messages |
| D7 | run 6, TC8 | The Treasurer crashed on restart while rebuilding its funding table from a bit-flipped Allocation | availability | Rebuild only from anchor-verified records; restart fuzz test (no crash in 30 offline corruption patterns) |

Harness issues, which were not product defects:
- A race in TC7: a worker finished before it was killed.
- Container name reuse in TC12.
- Two criteria clarified before the following run:
  - TC10's "minority" is evaluated per target.
  - TC12 checks records written after the repair, because quarantined records keep their unverifiable copies by design.

Both clarifications are dated in `TEST_PLAN.md`.

**Lesson.** TWGR itself was correct in every run. All four integrity defects (D2, D3, D4, D6) had the same root cause: **a coordinator trusted its own local storage after a fault**. The principle that fixed them is that local copies are evidence like any other: a coordinator acts only on records verified against write-time anchors, and only after repair. The in-process experiments (E10) could not reveal this, because they have no restarts. It is the main finding of the real-environment campaign.
