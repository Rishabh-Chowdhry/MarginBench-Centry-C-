# Stage 4 — Simulations, Experiments, Benchmark Design, and Validation

**Scope.** This stage contains the preregistered hypotheses and decision rules, the baselines, the synthetic experiment suite (E1–E7) with results and figures, the statistical methods, and the exact protocol for the real-agent experiments, which have not yet been run.

**Evidence labels:**
- **[SYNTHETIC]** results come from the deterministic simulator of Stage 3 with Bernoulli oracles of known ground truth. They test the algorithm and the system, not LLM agents.
- **[TO RUN]** marks cells that require real agents and models. No value is supplied for them, and none is extrapolated.

Every number in §6 is produced by `analysis/make_figures.py` from `results/raw/*.jsonl`. The full suite reruns with `experiments/run_all.sh` (about 1.5–2 h on 4 cores).

---

## 0. Changes forced by building Stage 4

1. **Budget-lease policy (Stage 3 defect).** The Stage 3 policy granted a fixed fraction (1/16) of ε per lease and spent polynomially within each lease. At W = 32 only 16 leases could ever be granted, so half the workers starved, and the centralized variant's leases shrank geometrically. The first scaling smoke test showed it: cooperative W = 32 was *slower* than W = 8. It is replaced by a **polynomial lease schedule**: lease n receives ε/(n(n+1)), split evenly over R registrations. It never exhausts, and Σ ≤ ε by construction (`test_poly_lease_schedule_never_exhausts_and_sums_below_eps`). The old policy is kept as ablation E5. Validity is unaffected, because Theorem 8 holds for any spending rule with Σ ≤ ε.
2. **Algorithm 1 is invalid as specified.** See E4.
3. **Ledger performance.** The tick now scans only leased slots. This gave a 3× simulator speed-up and is required for W = 32 runs. Stage 3's fault-injection experiment was rerun on the updated ledger (§6.8).

---

## 1. Preregistered hypotheses and decision rules

These were fixed after a 3-seed pilot of E2 only (needed to size runs and horizons) and before any full run. α_test = 0.05, with the Holm correction inside each hypothesis family.

| ID | Hypothesis | Test / estimate | Supported if | Refuted if |
|---|---|---|---|---|
| H-valid-sim | Every FRESCO configuration keeps P(false confirmation) ≤ ε = 0.05 on the boundary null, including under faults | Wilson 95% interval per configuration (E1, Stage 3 rerun) | lower bound ≤ 0.05 in **all** configurations | any lower bound > 0.05 |
| H-rules | Removing any single rule raises the false-confirmation rate above ε under its trigger | Wilson interval (Stage 3 rerun) | lower bound > 0.05 for each removed rule | otherwise (reported per rule) |
| H-alg1 | Algorithm 1 as specified (Wilson, ε/T) exceeds ε on the boundary null; the repaired variant (Clopper–Pearson, ε/KT) does not | Wilson interval (E4) | as stated | as stated |
| H-vs-Alg1 | At a matched oracle budget, LEXIS reaches k* at least as often as repaired Algorithm 1 | difference in P(reach k*), Wilson intervals (E4) | LEXIS interval not below Algorithm 1's | LEXIS significantly lower |
| H-speed | FRESCO time-to-k* falls with W; parallel efficiency at W = 32 ≥ 0.5 (strong scaling, RMST ratio) | bootstrap CI of RMST(1)/RMST(W) | CI lower bound at W = 32 ≥ 16 | CI upper bound < 16 |
| H-coop | At equal total ε and equal total executors, cooperative FRESCO reaches k* faster than (a) W independent ε/W runs and (b) one centralized scheduler | two-sided Mann–Whitney on censored time, Holm over 20 comparisons; RMST ratio and rank-biserial as effect sizes | Holm-p < 0.05 with ratio < 1 for most W ≥ 8 | no detected difference (reported as such, not as equivalence), or FRESCO slower |
| H-overhead | Coordination is negligible relative to LLM-scale slot times | messages per oracle call; ledger ops/s at W = 32 (E2) | ≤ 10 messages per call; ledger load ≤ 100 ops/s | otherwise |
| H-recover | After a ledger crash, worker crash or partition, throughput returns to ≥ 90% of its pre-fault level within 2 × outage duration | E6 timelines | as stated | as stated |
| H-cert | Level certificates cover: P(η_k ≥ μ_k ∀k) ≥ 0.95 | Wilson interval (E7) | lower bound ≥ 0.90 and point estimate ≥ 0.95 | point estimate < 0.95 |

A "no detected difference" result is never reported as equivalence. All negative results are reported.

---

## 2. Workloads (synthetic)

| Name | Levels 1–4: fraction of true violators π (p_good = 0.6) | k* | Use |
|---|---|---|---|
| S1-moderate | 0, 0, 0.05, 0.10 | 3 | strong scaling, H-coop, ablations, recovery |
| S2-sparse | 0, 0, 0.01, 0.05 | 3 | strong scaling and H-coop on a harder search |
| Weak(W) | 0, 0, 0.16/W, 0 | 3 | weak scaling: expected search work ∝ W |
| Null-boundary | every candidate p = α = 0.2 | — | validity (every confirmation is false) |
| Cert | 0.003 (p = 0.3), 0.01 (p = 0.3), 0, 0 | — | certificate coverage (μ > 0 but hard to confirm) |

- **Nulls.** Null candidates have p ~ U(0, 0.2), or exactly α in the boundary instances.
- **Latency.** Slot latency is lognormal (σ = 0.5) with mean 20 s if benign and 30 s if violating. This is the order of magnitude of a tool-using agent episode, but it is not a measurement.
- **Capacity.** Each worker has 4 executors, so every method compares at a total of 4W concurrent oracle calls.
- **Censoring.** Time is censored at H = 150,000 s of virtual time.

**Why synthetic.** The validity claims concern *any* stochastic oracle, so known ground truth (which candidates are null, μ_k, k*) is what makes coverage measurable. Real-agent runs (§8) can measure efficiency and fault profiles but never coverage, because the true p is unknown.

## 3. Baselines

| ID | Baseline | Implementation | Valid? |
|---|---|---|---|
| B0a | Manuscript Algorithm 1 as written: per-budget top-T confirmation, Wilson bound at ε/T | `fresco/baselines/alg1.py` (`wilson-T`) | **no** (E4) |
| B0b | Algorithm 1 repaired: Clopper–Pearson at ε/(KT) | `cp-KT` | yes, by a union bound |
| B1 | W independent single-worker FRESCO deployments, each with its own ledger, budget ε/W and 4 executors; combined b̂ = min over runs | `simulate_independent` | yes, by a union bound |
| B2 | Naive distributed: FRESCO with one rule removed (no dedup / fresh retry / arrival order / local budget) | `LedgerConfig.unsafe_*` | no (Stage 3, rerun §6.8) |
| B3 | Centralized scheduler: one worker process driving all 4W executors through the same ledger | `centralized()` | yes |
| B4 | ASHA-style successive-halving scheduler | **not implemented**. Any scheduler is valid under Theorem 1, so ASHA belongs in the scheduler ablations; it is left as future work | — |

## 4. Metrics
- **Time to target:** virtual time until b̂ = k* first holds. Censored at H.
- **Oracle calls to target:** calls leased up to that moment, or all calls by H if censored.
- **P(reach k* by H)**, and **P(any false confirmation)**.
- **Coordination:** messages per oracle call, and ledger operations per second.
- **Recovery:** time after the fault ends until throughput is back to 90% of the pre-fault mean; calls lost.
- **Certificates:** coverage P(η_k ≥ μ_k ∀k), and median η_k.

## 5. Statistical methods
- **Unit of analysis.** The independent run (seed). Seeds index common random numbers across methods: the same seed gives the same per-worker generator streams. Faults change trajectories, so runs are compared as independent samples, not as paired observations.
- **Censoring.** All runs share the administrative horizon H, so comparisons use the **RMST**, the mean of min(T, H). It is unbiased for the restricted mean and needs no assumption about the censored tail. Kaplan–Meier curves are used for display.
- **Intervals.** Percentile bootstrap with 4,000 resamples for means and ratios. Wilson intervals for proportions.
- **Tests.** Two-sided Mann–Whitney U with tie correction. Censored values are ties at H, which is valid under common censoring. Holm adjustment within each hypothesis family.
- **Effect sizes.** RMST ratio with CI, and rank-biserial correlation (+1 means FRESCO is always faster).
- **Validity claims** use the Wilson lower bound against ε, which is conservative toward rejecting validity.
- **Power.** With 100 seeds per cell and the heavy-tailed (roughly geometric) times seen in the pilot (coefficient of variation ≈ 1), a two-sample test has about 80% power to detect an RMST ratio of about 0.65. Smaller cooperative gains would go undetected, and the report says so where it applies.

---

## 6. Results [SYNTHETIC]

RESULTS_PLACEHOLDER

---

## 8. Real-agent experiment protocol [TO RUN — no results exist]

These experiments test what simulation cannot: real fault and latency profiles (H-valid-real), efficiency on real attack generators, utility trade-offs, and cross-model transfer.

### 8.1 Setup
- **Models.** At least two independently developed open-weight model families, each served with vLLM at a pinned revision. Seeded sampling makes replay mode possible. Add one API model only if its terms permit, with the API ID, date and settings recorded.
- **Scenarios.** MARGIN-Bench bundles (manuscript §5). The pilot uses 50 scenario families × 4 surfaces, with the authorization oracle and per-slot snapshot reset (A1) unit-tested first.
- **Generators.** A random admissible sampler (non-adaptive, also used for audits); a transformation library; and an adaptive PAIR/TAP-style generator. The adaptive one receives committed outcomes only (A2).
- **Executors.** `fresco.interfaces.Executor`: one sandboxed episode per slot, per-slot deadline, and a trace written to a content-addressed store.

### 8.2 Procedures
1. **Fault profiling (H-valid-real).**
   - Run 2,000 slots per model with deadlines disabled. Record the latency distribution separately for violating and benign trajectories, plus crash and timeout rates by outcome, in order to estimate (c₀, c₁).
   - Measure duplicate and redelivery rates for the queue technology a naive harness would use (Ray task retries, Celery `acks_late`).
   - Plug the measured rates into the Stage 3 fault-injection script and report the implied inflation for each removed rule. **Decision:** if the measured (c₀, c₁) differ by less than 0.02 and duplicates are below 0.1%, report that, in practice, the rules guard against rare events; otherwise report the measured inflation.
2. **Replay-determinism audit.** Re-execute 200 random DONE slots with the same key. Compare trace hashes, and keep replay mode only if 100% match.
3. **Efficiency.** FRESCO at W ∈ {1, 2, 4, 8, 16, 32} (or the largest W the GPUs allow) against B0b, B1 and B3 on 20 pilot families. Same metrics and statistics as §5. Clustering is by scenario family, with the cluster bootstrap over families.
4. **Utility and Pareto.** Authorized-task completion on the paired authorized counterparts (manuscript §7.5), reported next to b̂ per defender configuration.
5. **Transfer.** Witnesses confirmed on model A are re-confirmed on model B with fresh registrations and fresh keys, at level ε/(number of transferred witnesses).

### 8.3 Results shells (to be filled only from executed runs)
| Quantity | Model A | Model B | Required evidence |
|---|---|---|---|
| (c₀, c₁) timeout/crash by outcome | [TO RUN] | [TO RUN] | 2,000-slot profile |
| duplicate rate of the naive queue | [TO RUN] | [TO RUN] | broker logs |
| replay determinism (% hash match) | [TO RUN] | [TO RUN] | 200-slot replay |
| implied false-confirmation inflation per removed rule | [TO RUN] | [TO RUN] | Stage 3 script with measured rates |
| RMST time to b̂, FRESCO vs B1 vs B3, per W | [TO RUN] | [TO RUN] | 20 families, cluster bootstrap |
| b̂ per surface, with censoring fraction | [TO RUN] | [TO RUN] | per-surface ledger |
| authorized-task completion | [TO RUN] | [TO RUN] | paired counterparts |
| transfer rate of confirmed witnesses | [TO RUN] | [TO RUN] | fresh-key reconfirmation |

---

## 9. Figure catalogue (Phase 8): purpose and reading

| Figure | Shows | Supports the hypothesis if | Challenges it if |
|---|---|---|---|
| Fig. 1 strong scaling | RMST time to k* vs W, three methods, two scenarios | FRESCO tracks the ideal-linear line | it flattens early (Amdahl/critical path) or sits above the baselines |
| Fig. 2 speedup and weak scaling | RMST(1)/RMST(W) for FRESCO; weak-scaling efficiency | speedup ≥ W/2 at W = 32; weak efficiency ≈ 1 | efficiency falls steadily with W |
| Fig. 3 oracle calls | mean calls to reach k* vs W | calls roughly flat in W (parallelism costs little extra work) | calls grow with W (waste from overshoot, staleness, budget dilution) |
| Fig. 4 Kaplan–Meier, W = 8 | full time-to-target distributions | curves separate consistently | curves cross (a mean difference driven by the tail) |
| Fig. 5 coordination | messages per call; ledger ops/s vs W | both small and roughly flat or linear in W | super-linear growth |
| Fig. 6 validity | P(false confirmation) with Wilson CI for every method | all valid methods left of ε | any valid method crosses ε |
| Fig. 8 ablations | RMST ratio vs the default for each component | the defaults are not dominated | a simple setting dominates (reported) |
| Fig. 9 recovery | throughput timeline around faults | fast return to baseline | long or permanent loss |

There is no Fig. 7. The certificate results are a table (E7), because two variants with four levels each are clearer as numbers.

## 10. Reproduction
```
python3 -m pytest -q tests          # 42 tests
experiments/run_all.sh              # all experiments + figures (~1.5-2 h, 4 cores)
python3 -I analysis/make_figures.py # tables -> results/processed/summary.md, figures -> figures/
```
- Every result row carries its config hash and the run code revision (`results/raw/*.jsonl`, first line = manifest).
- The simulator is deterministic: the same config and seed give the same `trace_digest`.

## 11. Threats to validity of Stage 4
- **Synthetic oracles.** Latency, crash and duplicate parameters are assumptions. Real profiles may make the rule violations rarer, or worse.
- **Non-adaptive generator in the simulator.** H-coop and the scaling results concern random search inside reservoirs. Adaptive generators have sequential depth and could change the scaling (Proposition 12's critical path).
- **Four executors per worker and the lease parameters** are fixed defaults. E5 covers part of this sensitivity.
- **H-coop is tested against two particular baselines.** A smarter independent baseline (for example scouting-weighted spending) could close any gap.
- **Virtual time** ignores the coordinator's real CPU cost. That cost is measured separately as ops/s (E2) and must be checked against a real PostgreSQL ledger (not done).

## 12. Inputs to Stage 5 (manuscript)
The manuscript can claim only what §6–§7 support, labelled [SYNTHETIC]. The real-agent claims stay as placeholders until §8 is executed.
