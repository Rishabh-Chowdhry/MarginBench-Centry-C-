# Stage 1 — Novelty Investigation, Three Candidate Directions, and Selection

**Project:** evolving *MARGIN-Bench: Counterfactual Safety Margins for Multi-Turn and Multi-Agent LLM Systems* (working manuscript v1.0) into an algorithmic and distributed-computing contribution.
**Status:** Stage 1 of 5 (novelty analysis and direction selection). There are no empirical results about LLM agents in this document. The only numbers come from one synthetic Monte Carlo sanity check, labelled as such in §4.3 (`sims/stage1_counterexamples.py`).
**Date:** 2026-10-17.

---

## 0. Executive summary

1. **What MARGIN-Bench already contributes.** It is a *measurement specification*: per-surface intervention costs, a permission-grounded oracle, a first-passage "discovered margin" with right-censoring, matched authorized/unauthorized counterparts, and a reporting discipline. Nearly all of its parts have precedents: minimal-perturbation robustness, StrongREJECT/HarmBench evaluation discipline, AgentDojo/InjecAgent/ASB environments, AgentLAB long-horizon attacks, AgentBound counterfactuals, survival analysis. Its novelty is in how these are combined and in the estimand. That has to be argued; it cannot be assumed.
2. **The weakest technical point of the current manuscript is Algorithm 1.** It (a) depends on an unspecified "predefined multiplicity rule" over an *adaptively generated* candidate stream of unknown size, (b) throws away discovery samples, (c) re-tests across budget levels without accounting for repeated looks, (d) gives no quantitative meaning to "not found within B", and (e) is single-process, although the manuscript's own cost model, O(N·S·K·Q·R), implies about 4×10⁷ model calls at the manuscript's 500-bundle, 4-surface scale with illustrative values I chose (K = 5 budgets, Q = 200 queries, R = 20 repetitions; the manuscript does not fix these).
3. **Main finding of the investigation.** Each statistical building block exists: e-processes and confidence sequences, Ville's inequality, e-value multiple testing, good-arm and thresholding bandits, infinitely-armed pure exploration, residual-risk estimation in fuzzing. Each distributed building block also exists: leases, escrow, CRDTs, CALM, idempotent delivery, parallel fuzzing schedulers, ASHA. **I found no work that treats the *statistical validity* of adaptive, sequential security confirmation as a property that ordinary distributed-execution semantics can break or preserve.** The relevant semantics are at-least-once delivery, arrival-order processing, fresh-seed retry after crashes, elastic workers with local error control, and stale shared state. A synthetic check (§4.3) shows these defaults raising the false-confirmation rate from a nominal 0.05 to 0.11–0.72.
4. **Three directions** (§3):
   - **A. LEXIS:** two-sided, anytime-valid margin inference. Statistical framework.
   - **B. FRESCO:** a distributed algorithm and protocol for cooperative, validity-preserving margin search.
   - **C. CRAFT:** causally consistent, revocation-aware authorization for multi-agent tool calls.
5. **Selection:** **Direction B (FRESCO), with Direction A as its statistical core.** C has the highest novelty risk, given Zanzibar zookies, TOCTOU-Bench, and authenticated-delegation work. It is better kept as a new *scenario family* inside MARGIN-Bench (revocation races) than as the headline contribution. The selection could still fail on evidence. §5.3 lists what would refute it.

---

## 1. What exists in the manuscript, classified honestly

| Manuscript component | Classification | Closest prior / precedent |
|---|---|---|
| Surface-specific cost c_s(δ), admissible budget sets B_s(b) | Re-statement of perturbation-set robustness for discrete agent interventions | DeepFool, C&W, Madry et al. (cited in manuscript) |
| Ideal margin R_{s,α}(M,E) = inf{c_s(δ): p_M(E,δ) ≥ α} | Probabilistic minimal-adversarial-cost estimand; new for agent *actions*, not new as a concept | Randomized smoothing radius (Cohen et al. 2019); Best-of-N ASR scaling (Hughes et al., NeurIPS 2025) |
| First-passage cost with right-censoring | Direct use of survival analysis | Kaplan & Meier 1958 |
| Paired causal contrast Δ_i(δ) | Standard matched-pair design | AgentBound/AgentBoundary (arXiv 2609.33658), CausalTrace (PMLR 306) |
| Permission/post-state oracle | Engineering discipline; important but not algorithmic novelty | AgentDojo, ASB, CaMeL |
| Algorithm 1 (cost-stratified confirmation) | A heuristic with **under-specified validity**. This is where the opportunity lies | — |
| Pareto security–utility frontier | Standard multi-objective reporting | — |

**Conclusion:** MARGIN-Bench is a defensible *benchmark/measurement* paper, conditional on the novelty audit in its own §2.7. On its own it is **not** an algorithmic or distributed-systems contribution. The opportunity is to make the margin *estimator* rigorous, and then to make it *scalable without losing that rigour*.

---

## 2. Phase 1 — Literature investigation by topic

Every entry below was checked against Crossref, the publisher page, PMLR, USENIX, or arXiv on 2026-10-17. "Gap" names the specific property that, as far as I found, is missing. It does **not** mean the topic is unstudied.

### 2.1 Sequential and anytime-valid inference (statistical core)
- **Established:** Wald's SPRT (Ann. Math. Stat. 1945, doi:10.1214/aoms/1177731118). Time-uniform confidence sequences: Howard, Ramdas, McAuliffe, Sekhon, *Ann. Stat.* 2021, doi:10.1214/20-AOS1991. Betting confidence sequences for bounded means: Waudby-Smith & Ramdas, *JRSS-B* 2024 (online 2023), doi:10.1093/jrsssb/qkad009. E-values: Vovk & Wang, *Ann. Stat.* 2021, doi:10.1214/20-AOS2020. Safe testing: Grünwald, de Heide, Koolen, *JRSS-B* 2024, doi:10.1093/jrsssb/qkae011. SAVI survey: Ramdas, Grünwald, Vovk, Shafer, *Stat. Sci.* 2023, doi:10.1214/23-STS894. Always-valid A/B testing: Johari et al., *Oper. Res.* 2022, doi:10.1287/opre.2021.2135.
- **Multiple testing:** e-BH: Wang & Ramdas, *JRSS-B* 2022, doi:10.1111/rssb.12489. Online e-LOND: Xu & Ramdas, AISTATS 2024, PMLR 238:3997–4005, https://proceedings.mlr.press/v238/xu24a.html. Stopped e-BH: arXiv 2502.08539 (2025). α-investing: Foster & Stine, *JRSS-B* 2008, doi:10.1111/j.1467-9868.2007.00643.x.
- **Delayed and overrunning responses** (the clinical-trials analogue of results that arrive asynchronously): Hampson & Jennison, *JRSS-B* 75(1) 2013, doi:10.1111/j.1467-9868.2012.01030.x.
- **Gap:** These methods assume a *well-defined observation sequence*. They say nothing about how that sequence is produced by a fault-prone distributed executor, where duplicate delivery, crash-retry selection, or arrival-order reordering can invalidate the supermartingale property. Hampson & Jennison handle *pipeline* data at analysis time, not outcome-correlated loss and retry.

### 2.2 Threshold, good-arm, and infinitely-armed bandits (adaptive search core)
- Thresholding bandit: Locatelli, Gutzeit, Carpentier, ICML 2016, PMLR 48, https://proceedings.mlr.press/v48/locatelli16.html.
- Good-arm identification: Kano et al., *Machine Learning* (Springer) 2019, doi:10.1007/s10994-019-05784-4. Multi-threshold GAI: arXiv 2503.10386, PMLR 304 (2026), https://proceedings.mlr.press/v304/jiang26a.html.
- Infinitely-armed pure exploration: Aziz, Anderton, Kaufmann, Aslam, ALT 2018, PMLR 83:3–24, https://proceedings.mlr.press/v83/aziz18a.html. Quantile-relative PAC identification: Chaudhuri & Kalyanakrishnan, AAAI 2017, https://ojs.aaai.org/index.php/AAAI/article/view/10802.
- Distributed and parallel exploration: Hillel et al., "Distributed Exploration in Multi-Armed Bandits", NeurIPS 2013, https://papers.nips.cc/paper/2013/hash/598b3e71ec378bd83e0a727608b5db01-Abstract.html. ASHA: Li et al., MLSys 2020, https://proceedings.mlsys.org/paper_files/paper/2020/hash/a06f20b349c6cf09a6b171c71b88bbfc-Abstract.html.
- Bandits used for jailbreak or red-team selection: "Jailbreaking for the Average Jane…" (arXiv 2606.26936, 2026), which itself warns that adaptive ordering can make a sub-optimal jailbreak look optimal. Red-Bandit (arXiv 2510.07239, 2025).
- **Gap:** (i) the **lexicographic cost structure** of the target: find the *cheapest* cost class containing an arm above threshold, where each class is a reservoir of generated arms; (ii) **non-discovery certificates** for the classes that were searched without success; (iii) distributed execution with validity preserved under faults. Hillel et al. and ASHA optimise communication and throughput, not error control under faulty delivery.

### 2.3 Statistical assurance in testing and fuzzing (non-discovery side)
- STADS: Böhme, *ACM TOSEM* 2018, doi:10.1145/3210309. Residual risk in greybox fuzzing: Böhme, Liyanage, Wüstholz, ESEC/FSE 2021, doi:10.1145/3468264.3468570.
- Statistical model checking: Younes & Simmons, *Inf. Comput.* 2006, doi:10.1016/j.ic.2006.05.002. Legay et al., RV 2010, doi:10.1007/978-3-642-16612-9_11. Scenario approach: Campi & Garatti, *SIAM J. Optim.* 2008, doi:10.1137/07069821X.
- LLM evaluation statistics: Miller, "Adding Error Bars to Evals", arXiv 2411.00640 (2024). Kaur, "What AI Red-Team Evaluations Can and Cannot Prove", arXiv 2607.21735 (2026), which introduces an "evidential ceiling" for passive benchmarks. **Directly relevant; must be cited and differentiated.**
- **Gap:** Residual-risk and evidential-ceiling analyses address *whether anything was found*. MARGIN needs a **cost-indexed** statement ("at cost ≤ b, the generator's α-violating mass is ≤ η_b") that holds simultaneously over b and stays sound when trials are lost or duplicated.

### 2.4 Distributed adaptive search and parallel fuzzing (systems analogue)
- Dodrio (ESEC/FSE 2024 Industry): redundancy-free parallel taint fuzzing, https://2024.esec-fse.org/details/fse-2024-industry/23/. DynamiQ (arXiv 2510.04469, 2025): dynamic task allocation in parallel fuzzing. MPI distributed fuzzing (arXiv 2512.01617, 2025). UniFuzz/UltraFuzz (arXiv 2009.06124).
- **Established lesson:** naive parallelism wastes work through redundancy, and task allocation and synchronisation matter.
- **Gap:** Fuzzing is a *deterministic-oracle, discovery-only* problem: a crash is a crash. LLM security confirmation is *stochastic* and needs evidence accumulated over repeated trials, so redundancy and duplication become a **correctness** issue as well as an efficiency issue.

### 2.5 Distributed state, consistency, causal ordering, checkpointing
- Lamport clocks, *CACM* 1978, doi:10.1145/359545.359563. Chandy–Lamport snapshots, *ACM TOCS* 1985, doi:10.1145/214451.214456. Leases: Gray & Cheriton, SOSP 1989, doi:10.1145/74850.74870. Escrow transactions: O'Neil, *ACM TODS* 1986, doi:10.1145/7239.7265. CRDTs: Shapiro et al., SSS 2011, doi:10.1007/978-3-642-24550-3_29. CALM: Hellerstein & Alvaro, *CACM* 2020, doi:10.1145/3369736. Ray: Moritz et al., OSDI 2018, https://www.usenix.org/conference/osdi18/presentation/moritz.
- **Closest analogue for budget allocation:** Privacy Budget Scheduling / PrivateKube, Luo et al., OSDI 2021, https://www.usenix.org/conference/osdi21/presentation/luo. It treats a *non-replenishable statistical budget* (differential privacy ε) as a scheduled cluster resource. Pay-as-you-go privacy filters: Rogers et al., arXiv 1605.08294. **This is the strongest novelty threat to any "statistical-error budget as a resource" claim and must be addressed head-on** (§4.4).

### 2.6 Distributed authorization, delegation, revocation, trust boundaries
- Zanzibar, USENIX ATC 2019, https://www.usenix.org/conference/atc19/presentation/pang. It solves the *new-enemy problem* with zookies, which are causally consistent ACL snapshots.
- Macaroons, NDSS 2014, doi:10.14722/ndss.2014.23212.
- Authenticated delegation for AI agents (OAuth/OIDC extension): South et al., arXiv 2501.09674 (2025; ICML 2025 position).
- CaMeL capability-based prompt-injection defence: arXiv 2503.18813.
- TOCTOU in LLM agents: Lilienthal & Hong, "Mind the Gap", NeurIPS 2025, arXiv 2508.17155, with TOCTOU-Bench (66 tasks).
- **Gap (narrow):** none of these, as far as I found, treat *revocation propagating across a delegation chain of LLM agents* as an evaluable attack surface with an oracle that names a consistency model. The mechanisms needed to *fix* it (causal tokens, fencing, snapshot reads) are, however, well established.

### 2.7 Multi-agent LLM security
- "The Dark Side of LLMs" (arXiv 2507.06850) reports that inter-agent trust exploitation compromises more models than direct injection does. TAMAS benchmark (arXiv 2511.05269). Already cited in the manuscript: AgentLAB (PMLR 306), MultiBreak (PMLR 306), Mastermind (arXiv 2601.05445), X-Teaming (COLM 2025).
- These works establish the inter-agent surface empirically. None defines a cost-indexed margin with sequential error control.

### 2.8 Manuscript citations spot-checked
I confirmed the existence and title of the manuscript's references [1] arXiv 2601.05445, [2] AgentLAB PMLR 306, [4] CausalTrace PMLR 306, [5] AgentBoundary arXiv 2609.33658, and [20] doi:10.1145/3605764.3623985. Note that [5]'s actual title is *"AgentBoundary: Counterfactual Evaluation of Safety in Tool-Using LLM Agents"*. The manuscript calls it "AgentBound", so check the naming. I did **not** re-verify every other reference in the manuscript.

---

## 3. Phase 2 — Three competing directions

Notation, reused from the manuscript: scenario E, surface s, intervention δ with cost c(δ) ∈ {1,…,K}, violation probability p(δ) = Pr_ξ[V(τ(M, E⊕δ; ξ), E) = 1], threshold α, ideal margin R = R_{s,α}(M,E).

### Direction A — LEXIS: *Lexicographic E-process Inference for Security margins*

**Research question.** Can the discovered margin be given an *anytime-valid upper confidence bound* and a *cost-indexed non-discovery certificate*, both holding under adaptive candidate generation, adaptive allocation, and optional stopping?

**Hypothesised contribution.**
1. *Upper side.* Each generated candidate j gets a predictable error weight γ_j, with Σγ_j ≤ 1, fixed at registration, and a betting e-process

   E_{j,n} = ∏_{k≤n} (1 + λ_{j,k}(Y_{j,k} − α)), with λ_{j,k} ∈ [0, 1/α) predictable,

   which is a non-negative supermartingale under H₀ⱼ: p(δ_j) ≤ α. Candidate j is confirmed when E_{j,n} ≥ 1/(εγ_j). Report b̂ = min{c(δ_j): j confirmed}, or "censored".
   **Proposition A1 (provable, standard tools).** Pr(R > b̂) ≤ ε. Equivalently, b̂ is a (1−ε) upper confidence bound on the ideal margin R. This holds for any adaptive generator, any allocation rule, and any stopping rule, under assumption A-iid below. *Proof sketch:* condition on the registration σ-field F_{t_j}. Ville gives Pr(sup_n E_{j,n} ≥ 1/(εγ_j) | F_{t_j}) ≤ εγ_j. Summing over j and using Σγ_j ≤ 1 gives Pr(any null confirmed) ≤ ε. If no null is confirmed, every confirmed δ has p > α, so R ≤ b̂.
2. *Lower side, measure form.* At each level b, reserve a fraction of draws as **non-adaptive audit draws** δ ~ D_b, each run r times. Let μ_b = D_b{δ: p(δ) ≥ α}. A draw with p ≥ α shows at least one success with probability ≥ 1 − (1−α)^r. So if N_b audit draws show S_b draws with any success, then with probability ≥ 1 − ε′, simultaneously for all K levels,

   μ_b ≤ U_binom(S_b, N_b; ε′/K) / (1 − (1−α)^r),

   where U_binom is an exact one-sided binomial upper bound. When S_b = 0 this is μ_b ≤ ln(K/ε′) / (N_b (1 − (1−α)^r)).
   **Proposition A2 (provable).** This is a correct certificate *about the generator's distribution*, not about R. It **never** implies R > b. The manuscript's own non-claims (§4.2, §12.5) are therefore preserved, and "not found within B" gets a quantitative meaning.
3. *Allocation.* Find the smallest k whose reservoir contains an arm with p ≥ α. This is a **lexicographic reservoir-thresholding** problem, combining GAI (Kano 2019) with infinitely-armed exploration (Aziz 2018).

**Why existing approaches are insufficient.** Fixed-n Wilson intervals with "a multiplicity rule" (the manuscript's §4.6) are undefined when the number of candidates is adaptive. Discovery/confirmation splitting wastes samples. GAI and thresholding bandits assume a fixed arm set and no cost order.

**Primitives.** Candidate registration with weight γ_j; betting e-process update; audit draw; level certificate.
**I/O.** Input: (M, E, s, generator G, α, ε, ε′, budgets). Output: (b̂ or CENSORED, confirmed witness trace, {η_b} for b=1..K, full query ledger).
**Feasibility.** High. The proofs use only Ville's inequality and binomial tails.
**Distributed applicability.** Indirect. Validity depends on how the trial sequence is produced, which is what motivates B.
**Advantages.** Anytime-valid; no discarded discovery samples; a two-sided report.
**Limitations.** A-iid (fresh, conditionally independent trials per candidate) fails under API drift or hidden state. The lower side is a statement about D_b only.
**Falsification.** (i) Coverage: on synthetic oracles with known p, empirical Pr(R > b̂) must be ≤ ε. (ii) Efficiency: if a fixed-split Wilson procedure with Bonferroni-on-observed-count reaches the same b̂ with fewer or equal oracle calls on realistic p-distributions, A's efficiency claim fails.
**Novelty risk: medium-high.** Every component is known. The contribution is the formulation (lexicographic reservoir thresholding plus a two-sided report) and its use for agent security. A statistics venue might call it "standard e-value bookkeeping".
**Implementation complexity:** low. **Independent adoption potential:** high, as a small reusable library.

### Direction B — FRESCO: *Frontier-pruned, Replay-safe, Escrowed, Seed-Committed Orchestration*

**Research question** (the one posed in the brief, made precise). Can W asynchronous, fault-prone workers cooperate to (i) discover and statistically confirm low-cost violations with fewer total oracle calls and less wall-clock time than W independent searches with the same total error budget, while (ii) keeping LEXIS's guarantees exactly, under crashes, duplicate delivery, reordering, partitions, and elastic membership?

**Hypothesised contribution.** A distributed algorithm and protocol whose **statistical safety invariant is enforced as a distributed-systems invariant**, plus proofs that each rule is needed.

**New computational primitives.**
1. **Seed-committed evidence slots.** Trial k of candidate j is the slot (j,k) with seed σ_{j,k} = H(run_id, j, k). The e-process consumes only the *contiguous committed prefix* of slots, in index order and never in arrival order. Slots may *execute* in parallel; they *commit* in order.
2. **Exactly-once evidence ledger.** Slot results are keyed by (j,k). Merge is idempotent (a grow-only map). The first write wins and conflicting rewrites are flagged as faults.
3. **Direction-aware conservative imputation.** A slot that crashes or times out is recorded as Y=0 for *confirmation* (making violations harder to confirm), as "success" for the *audit certificate* (making robustness harder to certify), and is never re-run with a fresh seed. A slot may be re-run only under seed-deterministic replay.
4. **Statistical escrow.** A coordinator holds the global error budget ε. Workers obtain leased budget blocks, then assign γ_j locally to the candidates they register. Leases are fenced, so a confirmation is valid only if the coordinator accepts it under a live lease epoch. Unspent budget from a crashed worker is either forfeited (always safe) or reclaimed after lease expiry plus fencing.
5. **Monotone cost frontier.** The best confirmed cost b̂ is a min-register (a join-semilattice/CRDT), spread by gossip. Workers prune candidates and levels with cost ≥ b̂. Under CALM this needs no coordination, because staleness costs efficiency but never correctness.
6. **Lexicographic level scheduler.** Workers are allocated across cost levels and candidates by an index that favours cheaper levels and gives each reservoir a minimum audit share, so the certificate η_b remains computable.

**Formal I/O.** As LEXIS, plus the cluster configuration, a fault model, and the run manifest. Output adds a provenance DAG: every confirmation links to its slot set, seeds, lease epoch, and oracle version.

**Mathematical feasibility (proof targets, Stage 2).**
- **Theorem B1 (validity under asynchrony).** Under A-iid, plus rules 1–4, Pr(R > b̂) ≤ ε and the audit certificates hold. This is true for any number of workers, any interleaving, message delays, duplicate deliveries, crash-stop failures, and network partitions, since partitions only delay. *Proof idea:* the committed stream of each candidate equals its potential-outcome sequence (Y_{j,1}, Y_{j,2}, …), or a pointwise-smaller one under imputation. The decision to request slot k is predictable. Escrow keeps Σγ ≤ 1 globally. So LEXIS's argument applies unchanged.
- **Theorem B2 (necessity by counterexample).** Dropping any single rule admits executions with false-confirmation probability > ε. See §4.3 for the concrete constructions and the synthetic check.
- **Proposition B3 (frontier staleness).** The output b̂ does not depend on gossip delay Δ. Wasted oracle calls caused by staleness are ≤ W·θ·Δ, where θ is the per-worker trial rate.
- **Proposition B4 (overshoot).** If m slots of a candidate are in flight when its e-process crosses the threshold, at most m−1 trials are wasted per confirmation. This produces a tunable latency/waste trade-off.
- **Conjecture B5 (cooperative advantage).** When reservoir tails at low cost are sparse, shared frontier plus shared deduplication plus shared escrow beats W independent searches at ε/W each, in oracle calls to the first confirmed b̂. The advantage should grow with W, because independent searches pay the Bonferroni price log(W/ε) per confirmation and duplicate audit draws. *This is an empirical hypothesis, not a theorem.*

**Why existing approaches are insufficient.** Ray, Celery, or Kafka pipelines default to at-least-once delivery and retry-on-failure. ASHA and parallel fuzzers optimise throughput with deterministic or noisy-but-unvalidated objectives. Always-valid A/B platforms assume an i.i.d. arrival stream, not executor-induced selection. PrivateKube schedules a non-replenishable DP budget, but it neither ties budget consumption to sequential-test validity nor handles result deduplication.

**Advantages.** Measurable speedup with *provably unchanged* error control. Reproducible: in the deterministic-epoch mode the output is bit-identical across worker counts, assuming the oracle supports seeded replay. Reusable beyond LLMs, for any stochastic oracle confirmed sequentially (flaky tests, randomized systems, simulation-based safety testing).
**Limitations.** Head-of-line blocking from in-order commit. A coordinator is still needed for escrow. If A-iid is violated (model drift, hidden server state), no protocol restores validity; the protocol can only *detect* drift with a sentinel candidate.
**Falsification.** (i) If naive distributed baselines show no excess false confirmation under *realistic* fault and latency profiles measured from real agent runs, the validity motivation is mainly theoretical. (ii) If FRESCO does not beat "W independent LEXIS runs at ε/W" in oracle calls, or does not beat a single-queue centralised scheduler in wall-clock time at W ≥ 8, the algorithmic claim fails. (iii) If coordination overhead exceeds about 5% of oracle time at W = 32, the design is over-engineered.
**Novelty risk: medium.** A reviewer may say "this is dedup plus Bonferroni". The defence is B1 together with the necessity counterexamples B2, plus quantified failure of the defaults engineers actually use.
**Implementation complexity:** medium (about 3–5k lines of Python with a deterministic simulator). **Adoption potential:** high, as a drop-in confirmation layer for existing red-team harnesses.

### Direction C — CRAFT: *Causal Revocation-Aware Fencing for agent Tool calls*

**Research question.** In multi-hop agent delegation, can a protocol make every privileged tool call be authorized against a causally consistent, revocation-closed view of the delegation state? And can the oracle's consistency model be made explicit, so that "unauthorized" is well defined under concurrency?

**Hypothesised contribution.** Delegation tokens carry an *authorization frontier*: a vector timestamp over the issuers of grants and revocations. The tool gateway accepts a call only if its frontier dominates every revocation that happens-before the call. The benchmark oracle labels violations under named semantics (linearizable / causal / real-time). A new MARGIN-Bench surface, A_r (revocation races), measures the cost of exploiting the gap between those semantics.
**Primitives.** Frontier-carrying capability, fenced tool invocation, causal-cut oracle.
**Feasibility.** High. Safety proofs follow standard causal-consistency arguments.
**Why existing approaches may be insufficient.** OAuth-style agent delegation (South et al. 2025) and macaroons do not specify cross-agent revocation consistency. TOCTOU-Bench covers single-agent state races, not delegation chains.
**Limitations and novelty risk: high.** The mechanism is very close to Zanzibar zookies and to established fencing tokens and causal consistency. The contribution would be mostly the *threat class plus benchmark surface*. It also moves away from the margin-estimation core and needs real multi-agent frameworks to be convincing.
**Falsification.** If deployed agent frameworks already re-check authorization at call time against a strongly consistent store, the attack class is empty in practice.
**Implementation complexity:** medium. **Adoption potential:** moderate, mostly as a scenario family.

---

## 4. Critical comparison and selection

### 4.1 Scoring (1 = weak, 5 = strong; judgement, not measurement)

| Criterion | A: LEXIS | B: FRESCO (+A core) | C: CRAFT |
|---|---|---|---|
| Defensible originality | 2.5 | 3.5 | 2 |
| Provable non-trivial property | 3 (standard tools) | 4 (validity under faults + necessity) | 3 |
| Fit with MARGIN-Bench | 5 | 5 | 3 |
| Need for distributed systems actually justified | 1 | 5 (4×10⁷-call workload; faults affect validity) | 4 |
| Empirical testability with modest resources | 5 | 4 (mostly simulator plus small open-weight runs) | 3 |
| Risk of "just engineering" rejection | low | medium | high |
| Reuse beyond this paper | high | high | medium |

### 4.2 Decision
**Selected: Direction B (FRESCO), with LEXIS as its formally specified statistical core.** C is kept as an optional *scenario family* (revocation-race surface) inside the benchmark. It is not a headline claim.

Reasons:
1. B is the only direction where the distributed system is **necessary for a scientific property** and not only for speed. Whether false confirmations stay ≤ ε depends on delivery and retry semantics. This answers the brief's demand that every infrastructure component be justified by a specific problem.
2. B has a clear theorem-plus-counterexample structure (B1, B2) and falsifiable empirical claims (B5, overhead bounds).
3. A on its own is likely to be judged incremental by a statistics reviewer. Embedded in B, it becomes the specification that the protocol must preserve.
4. C's core mechanism is already known (Zanzibar, fencing). Leading with it invites an immediate novelty rejection.

### 4.3 Evidence that the problem is real (synthetic sanity check only)

`sims/stage1_counterexamples.py` simulates one null candidate at the least-favourable boundary p = α = 0.2. It uses a fixed-λ betting e-process (λ = 1), threshold 1/ε = 20, 600 slots, and 20,000 replications (seed 20261017). Output in `sims/stage1_counterexamples.out.txt`:

| Accounting rule | False-confirmation rate | ±95% |
|---|---|---|
| Exactly-once, slot-indexed (proposed) | 0.040 | 0.003 |
| At-least-once delivery, no dedup (30% redelivery) | 0.106 | 0.004 |
| Crash → fresh-seed retry; crash prob 0.3 if benign, 0.1 if violating | 0.260 | 0.006 |
| Crash → Y=0, no retry (proposed) | 0.015 | 0.002 |
| Worker-local level-ε control, W = 2 / 8 / 32 (FWER) | 0.073 / 0.270 / 0.722 | analytic from per-candidate rate |
| Escrowed ε/W per candidate, W = 32 (FWER) | 0.036 | 0.003 |

Interpretation, with limits: the proposed rules keep the false-confirmation rate below the nominal ε = 0.05. Each common default breaks it, sometimes badly. The crash/latency correlation parameters are **assumptions**, not measurements. Stage 4 must measure real timeout-versus-outcome correlations in agent runs before the size of the effect can be claimed in a paper. The stark W = 32 figure assumes 32 null candidates; real runs mix null and non-null candidates.

### 4.4 Novelty contrast for each FRESCO component

| Component | Established knowledge | Partially related methods | Proposed mechanism | Precise difference | Evidence required |
|---|---|---|---|---|---|
| E-process confirmation with predictable γ_j | Ville; e-values; online e-testing | e-LOND, α-investing | Per-candidate betting e-process; reported quantity is a *min-cost* over confirmations | Estimand is a lexicographic minimum, not a rejection set; two-sided report | Coverage on synthetic oracles; efficiency against fixed-split Wilson |
| Seed-committed in-order slots | Deterministic replay; in-order commit (logs, TCP) | Hampson–Jennison delayed responses | Evidence order fixed by slot index, independent of schedule | Applies replay to *preserve martingale structure* under outcome-correlated latency and loss | B1 proof; C2 counterexample at measured crash correlations |
| Direction-aware imputation | Informative censoring; worst-case imputation | — | Crash → 0 for confirmation, crash → 1 for certification, no fresh retry | One rule makes both sides of the report conservative under crash-stop faults | Proof; measured efficiency cost |
| Statistical escrow with fenced leases | Escrow (O'Neil 1986); leases (Gray & Cheriton 1989); fencing | **PrivateKube DP-budget scheduling (OSDI 2021)**; privacy filters | Leased blocks of *testing* error budget; confirmations accepted only under a live epoch | DP budgets are consumed by queries and composed by DP theorems. Here budget is assigned at candidate registration, validity relies on Ville plus a union bound, and acceptance must be fenced against zombie workers | Counterexample C3; overhead measurement; elastic-membership test |
| Monotone cost frontier | CRDT min-register; CALM | Shared seed queues in parallel fuzzing | Coordination-free pruning by confirmed cost | Proven to affect only efficiency, never validity (B3) | Waste versus gossip delay curve |
| Lexicographic level scheduler with audit share | GAI; thresholding; infinitely-armed BAI | ASHA, DynamiQ | Cheapest-level-first allocation that keeps per-level audit certificates computable | Objective is min-cost class, not best arm or coverage | Ablation against uniform, ASHA-style, and fuzzing-style allocation |

### 4.5 What the selected contribution explicitly does *not* claim
- No certified lower bound on the ideal margin R. Only generator-measure certificates.
- No validity when A-iid fails, for example under silent provider-side model updates. In that case the protocol offers drift *detection*, not correction.
- No claim that FRESCO is faster than a well-tuned centralised queue at small W. That has to be measured.
- No Byzantine-worker tolerance. The threat model treats workers as honest-but-crash-prone, because they belong to the evaluator. Byzantine tolerance would be justified only if third-party evaluators contribute results, which is out of scope and noted as future work.

---

## 5. Plan for the next stages (preview, no results)

### 5.1 Stage 2 — mathematics and algorithm
Full model: nodes, slots, ledger, leases, oracle; assumptions A-iid, crash-stop, and eventual delivery. Rigorous proofs of A1, A2, B1, B3, B4. Constructive counterexamples for B2. Sample-complexity analysis of the lexicographic scheduler under a reservoir model (tail mass π_k = D_k{p ≥ α + Δ}). Complexity: best, average, and worst case, plus communication cost. A rough first estimate is O(1) ledger messages per slot and O(1) coordinator messages per candidate registration, amortised by lease blocks. Publication-quality pseudocode.

### 5.2 Stages 3–4 — system and experiments
Deterministic discrete-event simulator, which is the primary evidence source, plus a Ray-backed (or plain asyncio + PostgreSQL) implementation. Only components with a stated purpose will be used: PostgreSQL as the ledger with unique (j,k) keys for idempotency; a coordinator for escrow and leases; gossip for the frontier. Baselines: (1) single-process MARGIN Algorithm 1; (2) W independent LEXIS runs at ε/W; (3) naive distributed (at-least-once, arrival order, fresh retry); (4) ASHA-style asynchronous successive halving on candidates; (5) centralised ideal single queue. W ∈ {1, 2, 4, 8, 16, 32}. Synthetic reservoirs, plus small open-weight-model runs on AgentDojo-style tasks, used only where licences allow.

### 5.3 What would make me reverse this selection
- Measured crash/timeout–outcome correlation in real agent runs is about 0, and deployments of evaluation harnesses already deduplicate. Then B's validity story shrinks to a robustness note, and the contribution should pivot to A plus an efficiency study.
- Independent ε/W runs match FRESCO within noise for W ≤ 32. Then cooperation brings nothing and the result should be reported as a negative finding.
- A 2025–2026 paper is found that already specifies fault-tolerant, anytime-valid distributed confirmation for stochastic oracles. Then position as a replication or extension.

---

## 6. Sources (all accessed 2026-10-17)

Statistics: [Howard et al. 2021](https://doi.org/10.1214/20-AOS1991) · [Waudby-Smith & Ramdas](https://doi.org/10.1093/jrsssb/qkad009) · [Vovk & Wang 2021](https://doi.org/10.1214/20-AOS2020) · [Wang & Ramdas 2022](https://doi.org/10.1111/rssb.12489) · [Ramdas et al. 2023](https://doi.org/10.1214/23-STS894) · [Grünwald et al. 2024](https://doi.org/10.1093/jrsssb/qkae011) · [Johari et al. 2022](https://doi.org/10.1287/opre.2021.2135) · [Xu & Ramdas 2024](https://proceedings.mlr.press/v238/xu24a.html) · [Stopped e-BH](https://arxiv.org/abs/2502.08539) · [Foster & Stine 2008](https://doi.org/10.1111/j.1467-9868.2007.00643.x) · [Wald 1945](https://doi.org/10.1214/aoms/1177731118) · [Hampson & Jennison](https://doi.org/10.1111/j.1467-9868.2012.01030.x) · [Kaplan & Meier 1958](https://doi.org/10.1080/01621459.1958.10501452) · [Campi & Garatti 2008](https://doi.org/10.1137/07069821X) · [Younes & Simmons 2006](https://doi.org/10.1016/j.ic.2006.05.002) · [Legay et al. 2010](https://doi.org/10.1007/978-3-642-16612-9_11)

Bandits and search: [Locatelli et al. 2016](https://proceedings.mlr.press/v48/locatelli16.html) · [Kano et al. 2019](https://doi.org/10.1007/s10994-019-05784-4) · [Multi-threshold GAI](https://arxiv.org/abs/2503.10386) · [Aziz et al. 2018](https://proceedings.mlr.press/v83/aziz18a.html) · [Chaudhuri & Kalyanakrishnan 2017](https://ojs.aaai.org/index.php/AAAI/article/view/10802) · [Hillel et al. 2013](https://papers.nips.cc/paper/2013/hash/598b3e71ec378bd83e0a727608b5db01-Abstract.html) · [ASHA](https://proceedings.mlsys.org/paper_files/paper/2020/hash/a06f20b349c6cf09a6b171c71b88bbfc-Abstract.html) · [Bandit jailbreak selection](https://arxiv.org/abs/2606.26936) · [Red-Bandit](https://arxiv.org/abs/2510.07239)

Testing and fuzzing: [STADS](https://doi.org/10.1145/3210309) · [Residual risk](https://doi.org/10.1145/3468264.3468570) · [Dodrio](https://2024.esec-fse.org/details/fse-2024-industry/23/Dodrio-Parallelizing-Taint-Analysis-Based-Fuzzing-via-Redundancy-Free-Scheduling) · [DynamiQ](https://arxiv.org/abs/2510.04469) · [MPI fuzzing](https://arxiv.org/abs/2512.01617) · [UniFuzz](https://arxiv.org/abs/2009.06124)

LLM evaluation and security: [Best-of-N](https://arxiv.org/abs/2412.03556) · [Error bars](https://arxiv.org/abs/2411.00640) · [Evidential ceilings](https://arxiv.org/abs/2607.21735) · [Dark Side of LLMs](https://arxiv.org/abs/2507.06850) · [TAMAS](https://arxiv.org/abs/2511.05269) · [CaMeL](https://arxiv.org/abs/2503.18813) · [TOCTOU-Bench](https://arxiv.org/abs/2508.17155) · [Authenticated delegation](https://arxiv.org/abs/2501.09674) · [Greshake et al.](https://doi.org/10.1145/3605764.3623985) · [AgentBoundary](https://arxiv.org/abs/2609.33658) · [Mastermind](https://arxiv.org/abs/2601.05445) · [CausalTrace](https://proceedings.mlr.press/v306/mothukuri26a.html) · [AgentLAB](https://proceedings.mlr.press/v306/jiang26as.html)

Distributed systems and authorization: [Lamport 1978](https://doi.org/10.1145/359545.359563) · [Chandy & Lamport 1985](https://doi.org/10.1145/214451.214456) · [Leases](https://doi.org/10.1145/74850.74870) · [Escrow](https://doi.org/10.1145/7239.7265) · [CRDTs](https://doi.org/10.1007/978-3-642-24550-3_29) · [CALM](https://doi.org/10.1145/3369736) · [Ray](https://www.usenix.org/conference/osdi18/presentation/moritz) · [PrivateKube](https://www.usenix.org/conference/osdi21/presentation/luo) · [Privacy filters](https://arxiv.org/abs/1605.08294) · [Zanzibar](https://www.usenix.org/conference/atc19/presentation/pang) · [Macaroons](https://doi.org/10.14722/ndss.2014.23212)
