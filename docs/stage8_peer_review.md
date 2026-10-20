# Stage 8 — Skeptical peer review

**Manuscript.** "Execution Semantics Are Statistics: Execution Rules and Self-Repairing Evidence for Valid Security Evaluation of LLM Agents". Reviewed in its Springer Nature version (`paper/springer/manuscript_sn.pdf`, 32 pp.); the LNCS Word version (`paper/lncs/manuscript_lncs.docx`) has the same content.

**Reviewer stance.** This review was written as a hostile but fair referee would write it. It is an internal review by the same AI assistant that helped build the work. That is a conflict of interest, and an external human review is still needed. Every factual claim below was checked against the repository at the commit of this file. Where a point is a judgement rather than a checked fact, it says so.

**Recommendation.**
- *Journal:* major revision.
- *LNCS proceedings, as it stands:* reject. The paper is about twice the usual page limit and holds at least two papers (Section 6).

---

## 1. Summary of the claims

The paper argues that the execution semantics of a distributed evaluation harness are part of the statistical protocol of agent security evaluation. Its claims are:

- **C1, the rules.** Six execution rules (R1–R6). Under them, sequential e-process confirmation and fixed-sample Clopper–Pearson confirmation keep their nominal error under network and process faults.
- **C2, necessity.** Common executor defaults (redelivery, fresh-key retry, arrival-order consumption, worker-local budgets) break validity, in simulation up to 0.999.
- **C3, the audit.** The MARGIN-Bench Algorithm 1 estimator, as specified, has 0.257 false confirmation at a nominal 0.05. An exact repair fixes it.
- **C4–C5, cost and guidance.** The rules are cheap, and a shared coordinator buys no speed.
- **C6, storage.** QUINTET is five single-writer coordinators over a hash-anchored evidence graph. Two repair algorithms come with it:
  - TWGR: no fabrication while honest anchor domains are a majority (tight);
  - TWGR-S: with device signatures and derivation dominance, no added confirmation with all coordinators compromised.
- **Testing.** A Docker SQA campaign with real faults (24/24 final).
- **Real agents.** Experiments on 10 small open-weight agents in AgentDojo show that attack success occurred only after the injected text reached the agent.

The writing is careful and unusually candid about negative results: Table 5 lists five unsupported or refuted hypotheses. Reproducibility material is extensive, and failing runs are kept. These are real strengths. The concerns below are about whether the contributions are as novel, as general and as well evidenced as the framing says.

---

## 2. Major concerns

### M1. The core theory (C1–C2) is close to folklore, and the paper half-admits it
"What is new" (§3) concedes that each mechanism and each inferential result is standard. What remains is the mapping between them:
- **Theorem 1** is Ville's inequality plus "the committed stream is a prefix".
- **Proposition 2** is stochastic dominance plus a union bound.
- **Theorem 3 (necessity)** gives one-line constructions, and its "proof" defers to the experiments.

None of this is wrong. But a statistics or systems referee will say that "don't count duplicates, don't peek, don't retry with fresh randomness, and use one budget" is known practice, from clinical-trial data monitoring, A/B-testing hygiene and exactly-once stream processing.

The paper needs one of two things:
- **(a)** evidence that real, widely used agent-evaluation harnesses actually violate these rules. The paper has none; it is listed under Future Work, and Table 8 still has *Redelivery rate of a naive queue: TO RUN*;
- **(b)** a non-obvious result, for example a tight characterisation of *when* a default breaks validity, rather than "there exists a fault pattern".

Without (a), C2 shows that the defaults *can* hurt, under fault rates the authors chose (§12 admits this: "the fault rates are chosen triggers, not measurements").

**Requested:**
- Audit at least two public harnesses (e.g. the AgentDojo runner, Inspect, HELM-style runners, or Ray/Celery-based pipelines). Report their delivery, retry and budget semantics, and the measured redelivery and timeout-by-outcome rates.

### M2. The headline security claim of TWGR-S assumes the problem away at the boundary that matters
Theorem 6 says that with *all five* coordinator domains compromised, repair adds no confirmation. The assumptions carry the result:

1. **Honest devices.** The executor device holds an uncompromised key, signs only what it observes, and signs at most one outcome per slot. §2 places the executor next to an *untrusted* sandboxed subject, and §7 says compromised devices "remain oracle-integrity failures outside the model". The guarantee is therefore end-to-end origin authentication: data signed at the source cannot be forged downstream. That is the standard argument of signed-provenance systems (in-toto, SLSA, TUF, Certificate Transparency), none of which are cited.
2. **The manifest.** It must be published *before the run, outside every coordinator domain*. The paper never says who publishes it, where, or how a verifier obtains it authentically. Any party that can substitute the manifest defeats the theorem.
3. **At-rest versus in-run compromise.** The theorem's conclusion is "every reported confirmation was also made by the original run". That bounds the error by the original run's error *only if the original run was itself valid*. Its validity (Theorem 1) needs R1: keys revealed only on lease. In the code, the Registrar holds the run key, and verification also uses it (`fresco/hkg/repair.py`, `admissible`, which recomputes `prf_key(params.run_key, …)`). An adversary in the Registrar *during* the run can therefore reveal keys early to the generator, the R1/R2 attack of Theorem 3(5). The original run is then invalid, and TWGR-S faithfully preserves its invalid confirmations. The theorem therefore covers *after-the-fact tampering with stored evidence*, not "any number of coordinators compromised", as the abstract and C6 state. The scope must be stated precisely.
4. **The robust rule is capped.** A confirmation must hold for every 0/1 assignment of its unsigned crash slots, and with more than 12 such slots it is refused (`MAX_UNSIGNED = 12`). This is safe. But its *power cost in live runs* is never measured: TC3 produced 122 and TC6 136 unsigned crash slots per run. The cap is an arbitrary constant, and enumeration is O(2^12) per candidate. A monotone bound, or a branch-and-bound over the e-process, would scale; the paper should either give one or justify the constant.

**Requested:**
- Restate Theorem 6's threat model as "stored evidence modified after it was written, by any set of coordinator domains".
- Add the in-run case as an explicit non-claim, or extend R1 so that keys are derived on the device, not the Registrar.
- Specify manifest publication and verification.
- Cite and compare with signed-provenance and transparency-log work.
- Report the confirmation-power loss of the robust rule under the TC3/TC6 crash rates.

### M3. The distributed-storage contribution ignores the literature it competes with
TWGR's guarantee is that a value is accepted if a strict majority of the domains holding write-time commitments vote for its digest, plus derivation. Byzantine quorum systems (Malkhi & Reiter), authenticated data structures and Merkle-tree audit logs, self-healing and scrubbing storage (ZFS, Ceph deep scrub), and erasure-coded integrity are not cited. The tightness remark ("any voting scheme accepts a majority adversary's value") is well known.

The paper's own ablation also undercuts the novelty of the claimed new combination:
- per-domain voting made **no difference** under random corruption (H7-ablate, not supported);
- derivation added only 0.010 recovery at ρ = 0.3;
- the witness replicas did almost all the work (0.215), and they are plain replication.

So under random faults TWGR is mostly "three copies plus digests". Under adversarial faults, its distinctive part (domain voting) fails exactly at the majority boundary, and the fix is signatures (M2). A reviewer will ask what remains of TWGR as a contribution.

**Requested:**
- A related-work paragraph on Byzantine quorums, authenticated logs and storage scrubbing.
- A baseline that is simply "3 replicas + a per-record signature or MAC + recompute derived records". If TWGR-S does not beat that baseline, the paper should say that the baseline is the recommendation.

### M4. The SQA campaign is a development log, not an independent validation
The campaign ran 11 times, and the final 24/24 is the run after seven service defects (D1–D7) and three admissibility issues (L1–L3) were fixed. The fixes were driven by the very test cases they were then evaluated on. Pass criteria received several dated post-hoc clarifications (`realenv/TEST_PLAN.md`):
- TC10 "minority" redefined per target;
- TC12 scoped to post-repair records;
- "wrong" redefined as wrong *content*, with link-byte differences reported separately;
- TC10 extended to k = 1…5 after the loophole fix.

Each is defensible, and all are disclosed. Together, however, they mean the final pass is not evidence of correctness: it is evidence that the implementation now passes its own regression suite. In addition:
- **One run per case** on one host. No repetition and no failure rates under faults are reported, only PASS/FAIL.
- **"Real" faults are local.** The network faults are Toxiproxy on one VM; there is no geographic latency, clock skew or disk-level faults (e.g. fsync loss or torn writes). Storage "corruption" is a script editing files while the containers are stopped.
- **The adversary is self-designed.** TC10 and E11 use attacks that the authors designed and the defence was built against: consistent forged values written everywhere the adversary holds a domain. No adaptive or adversarially searched attack was run. Examples: replaying a device's genuine signed result into a different run whose run_id collides; withholding chosen signed 0s so that the remaining signed 1s cross the threshold. The robust rule may or may not cover that case. Fuzzing the admissibility checks is another.

**Requested:**
- A held-out test campaign: new test cases, written after the code was frozen, ideally by someone else.
- Repeated runs (≥ 5) per fault case, with failure rates.
- At least one adaptive attack search against TWGR-S, e.g. property-based search over the adversary's choices.
- Explicit discussion of the selective-withholding case under the robust rule.

### M5. The real-agent results are small, and the strongest one is close to a tautology
- **Scale and models.** All agents are ≤ 8B open-weight models on CPU. E13 has 0/60 violations, E14 0/97 for the 1.5B agent, and E15 has 24 attacked episodes per agent, with intervals up to 0.36. No frontier or API model, and no model tuned for tool use, was evaluated. The attack set is a single AgentDojo attack (`important_instructions`).
- **"Every success required exposure"** (5/5 successes among 45 exposed, 0/195 unexposed) is close to definitional. An indirect prompt injection *cannot* act unless its text enters the context. The useful finding is the measurement point: that many "0 % attack success" numbers for small models reflect *non-exposure* and *tool-call format failure*, not robustness. The paper should lead with that, and drop the implication that exposure is an empirical discovery.
- **The exposure definition decides the result.** Exposure is computed by matching the injected text in tool outputs. Paraphrased or partially truncated injections would be missed. The exact matching rule and a sensitivity check are needed.
- **H-valid-real is untested.** The link between the real-agent sections and the paper's thesis (execution semantics inflate error in practice) is still missing. E13 measured outcome-dependent timeouts only for *task success*, not for violations (c0, c1 "not estimable"). The real-agent part currently supports a different paper: on evaluation hygiene for tool-use benchmarks.
- **The capacity check confounds two things.** The 1.5B→7B comparison changes both model size and tool-call reliability. The McNemar test (p = 0.007) concerns task success, not violations.

**Requested:**
- At least one stronger model with native tool calling.
- Violation-conditional timeout rates from that model, testing H-valid-real.
- A second attack type.
- Exposure matching rules with a sensitivity analysis.
- Reframe the exposure result as a reporting recommendation.

### M6. The LLM judge adds little and is presented generously
- κ = 0.19 on the main "no tool use" label, κ 0.20–0.41 on the finer behaviours, and 78 % self-consistency at T = 0.7.
- The paper rightly says counts come from trace facts. But Fig. 6 (left) and the E14 narrative still feature the judge's taxonomy.
- The judge (Qwen2.5-7B) is the same model as the E14/E15 capacity-check agent. If it also judged those episodes, that is self-evaluation and must be disclosed or avoided.
- No human annotation exists. κ against a rule classifier written by the same authors is not validation of either.

**Requested:**
- A small human-labelled sample (e.g. 50 episodes, two annotators) to validate both the judge and the rule classifier.
- Otherwise, move the judge to an appendix.

---

## 3. Minor concerns and errors found

1. **Inconsistent number.** TWGR recovery at ρ = 0.6 is 0.807 in §9.7 *Safety* but 0.804 in *Recovery*. The data (`results/processed/stage7_summary.md`) say 0.8070. Fix the 0.804.
2. **Defect counts disagree with the repository.** The paper says four of the seven defects were integrity defects. `realenv/RESULTS.md` classes D5 (id reuse) as integrity as well, which makes five. Reconcile.
3. **Stale number in the stage notes.** `docs/stage7_quintet_hkg_twgr.md` §4b says 324/324 forged Confirmations; the paper and the final data say 327/327. The 324 is from an earlier E11 run.
4. **Test count.** The paper says 73 tests; the repository has 74 `test_` functions. Update or say "over 70".
5. **Abstract overstatement.** "Defaults raised false confirmation … to 0.08–0.999" omits that the worker-local-budget default did *not* establish inflation at system level for sequential tests (0.065 [0.045, 0.094]; H-rules supported for 3 of 4).
6. **Plug-in Kelly monotonicity.** The proof of Theorem 5 relies on the plug-in e-process not being monotone in individual outcomes, which is why the "all consumed Results accepted" guard exists. The sketch of Theorem 6 uses "zero outcomes never raise the wealth of a non-negative bettor", which is true *at that step*. But with a plug-in λ, a 0 earlier changes later bets. The robust enumeration handles this inside T's length. The argument for slots *beyond* T's end should be written out in the main text, not deferred to internal notes ("Stage 7 notes, §4b"). A journal will not accept a proof that lives in an unpublished repository document.
7. **Boundary-null design.** Every null in the validity tests sits at p = α exactly. This is the worst case for most tests, but not obviously for the plug-in betting e-process, whose bet size adapts. A sweep over p ∈ [0, α] would cost little and remove the doubt.
8. **Seeds shared across methods** (§12). Paired comparisons need paired tests. Check that the Wilson/Newcombe intervals used are appropriate for correlated samples.
9. **Virtual time.** Coordination cost and scaling (25.4×) are measured in simulator virtual time. Say so in the abstract or the C4 statement, not only in §12.
10. **Two placeholders remain** (Table 8: *TO RUN*), plus author, affiliation, funding, CRediT, competing-interest and archive-DOI placeholders. A submission cannot contain them.
11. **References dated 2026** (`marginbench2026`, `jiang2026agentlab`, `kaur2026ceiling`, `yang2026agentboundary`, `mothukuri2026causaltrace`, `li2026mastermind`). Each must be checked against the published version, with a DOI or arXiv id. MARGIN-Bench is the paper's audit target, so its citation must be exact and the audited version identified.
12. **Disclosure of AI assistance.** The declarations correctly flag substantial AI assistance. Springer Nature policy requires this to be described in the Methods or Acknowledgements, and AI tools cannot be listed as authors. Make the disclosure specific: design, code, analysis and text.
13. **Terminology load.** QUINTET, TWGR, TWGR-S, LEXIS, LEXIS-S, Algorithm 1, E1–E15 and H7-*: a reader needs a glossary. Several H-labels in Table 5 (e.g. H6-noninf) are not defined in the text.
14. **Fig. 4 caption.** It describes "left/right panel" inside a sub-figure of a composite figure. Label the sub-panels (a)–(d).
15. **"Real controlled environment"** reads as an oxymoron. Prefer "containerised deployment with injected real faults".

---

## 4. Questions for the authors

1. Who holds the run key κ in deployment? Can keys be derived on the device, so that a compromised Registrar cannot leak them before lease?
2. How is the manifest published and authenticated? What happens to a run if one device key is revoked mid-run?
3. What fraction of live confirmations were refused by the 12-unsigned-slot cap in TC3 and TC6?
4. Did Qwen2.5-7B judge episodes in which it was also the agent?
5. Was any test case of the final campaign written after the code froze?
6. Under random corruption, does "3 replicas + signature + recompute derived records" recover as much as TWGR-S?

---

## 5. Assessment

| Criterion | Assessment |
|---|---|
| Originality | Moderate. The framing is new for agent evaluation; the parts and proofs are standard; the storage layer overlaps uncited literature. |
| Technical soundness | Proofs correct as far as checked, but the scope of Theorem 6 is overstated (M2.3), and one proof step lives outside the paper. |
| Empirical support | Strong for synthetic validity; weak for real-world relevance (no real-harness audit, small CPU models, no violation-conditional timeouts). |
| Reproducibility | Excellent: code, raw data and failing runs are all kept. |
| Clarity | Good prose, but too much in one paper, with a heavy acronym load. |
| Honesty about limits | Exemplary. |

**What would change the recommendation to accept:**
- the real-harness audit (M1);
- the corrected threat-model statement and a provenance baseline for TWGR-S (M2, M3);
- a held-out, repeated SQA campaign (M4);
- one strong tool-calling model with violation-conditional timeouts (M5).

---

## 6. Venue fit: Springer LNCS

LNCS proceedings usually allow **12–16 pages** in LNCS format, set by each conference; some allow extra pages for references or appendices. The manuscript is 32 pages in the journal template and 33 pages in the LNCS Word format. Cutting it to fit would remove the evidence the claims rest on. Two options:

1. **Split** it into
   - (a) *execution rules + audit* (§§1–6, 9.1–9.6; a statistics/evaluation venue), and
   - (b) *QUINTET + TWGR-S + SQA* (§§7, 9.7–9.8; a dependable-systems or security venue).

   The real-agent material (E13–E15) becomes a short workshop paper on exposure-aware reporting.
2. **Submit as a journal article**, for which the Springer Nature `sn-jnl` version already exists, and keep the LNCS version for a later, shortened conference paper.

The LNCS Word file delivered with this review (`paper/lncs/manuscript_lncs.docx`) is the **full** paper in LNCS styles, without shortening. Shortening it is an editorial decision for the authors.
