# Stage 5 — Independent Peer Review (Phase 10)

**Manuscript:** *FRESCO: Fault-Tolerant, Anytime-Valid Distributed Estimation of Counterfactual Security Margins for LLM Agents* (`paper/fresco_manuscript.tex`, working version of 18 Oct 2026).
**Review stance:** a skeptical referee for a Springer Nature security or distributed-computing journal (e.g. *International Journal of Information Security*, *Cluster Computing*). The reviewer and the authors are the same AI-assisted process. The review is written to be adversarial anyway, and it lists every weakness I could find, including those the manuscript already admits.

---

## 1. Summary of the submission
The paper argues that the statistical validity of sequential security confirmation for LLM agents depends on how a distributed harness executes episodes. It proposes:
- **LEXIS:** betting e-processes with error spending at registration;
- **FRESCO:** a ledger protocol with six rules;
- a theorem showing validity independent of scheduling, plus a necessity theorem.

The evaluation is entirely synthetic. FRESCO stays valid under faults, and removing a rule inflates error to 0.08–0.13. It scales to 25× at W = 32 with small coordination overhead. Cooperation gives no speed-up, and LEXIS is less sample-efficient than a repaired fixed design. The original MARGIN-Bench estimator is shown to be invalid (0.257 at nominal 0.05).

## 2. Recommendation
**Major revision. Not publication-ready in its current form.**

If a high-impact venue received it today, the likely outcome is rejection, for three reasons:
1. There is no evidence from real agents.
2. The core theory is a careful but standard application of Ville's inequality and a union bound.
3. The paper's own results undercut the case for the distributed *algorithm*: cooperation does not help, and the sequential procedure is less sample-efficient than the baseline it replaces.

The paper's real value — that execution semantics are part of the statistics — is genuine and useful. It needs a narrower framing and real-harness evidence (§9).

## 3. Ratings (1 = poor, 5 = excellent)
| Criterion | Score | Justification |
|---|---|---|
| Originality | **3** | The problem framing, the necessity counterexamples, and the audit of a published-draft estimator are new. Each mechanism (e-processes, leases, idempotency, in-order commit) is established, and Table 1 says so. |
| Methodological rigour | **4** | Preregistered hypotheses, ground-truth simulation, censoring-aware statistics and Holm correction. Negative results are reported. There is a single post-hoc variant, labelled exploratory. |
| Theoretical depth | **2.5** | Theorem 1 follows in a few lines from Ville's inequality, given the right filtration. Theorem 9's constructions are elementary. There is no lower bound for adaptive level scheduling and no efficiency theory for adaptive generators. |
| Empirical feasibility | **4** | The real-agent protocol is concrete and affordable: open-weight models, 2,000-episode profiling, 20 scenario families. |
| Reproducibility | **4.5** | Deterministic simulator, configuration hashes, committed raw data, one script that regenerates everything, and 42 tests. The PostgreSQL ledger and the real executor do not exist yet. |
| Potential significance | **3** | High *if* real harnesses show non-trivial correlation between timeouts and outcomes, or duplicate rates. Otherwise the rules become hygiene with little practical effect, and significance drops to about 2. |

## 4. Major concerns

### 4.1 Novelty rejection risk (high)
- **Theorem 1 is close to textbook.** A reviewer from the anytime-valid inference community will say:
  - per-hypothesis test supermartingales with predictable weights summing to ε give family-wise error control, by Ville plus a union bound;
  - "prefix-only bets" is just the definition of predictability;
  - the "full-sequence" argument is the standard observation that stopping cannot help an e-process.

  The paper must state plainly that the statistical result is not new. Its novelty is the mapping from executor semantics to the hypotheses of that result, and the necessity constructions.
- **Necessity constructions are elementary.** Duplicates squaring the wealth, selection by retry, and latency-sorted streams are each one-paragraph observations. Their value is practical, so the paper should support them with *measured* real-harness rates, not chosen triggers.
- **Overlap with privacy-budget scheduling.** Treating a non-replenishable statistical budget as a leased cluster resource (PrivateKube, OSDI 2021) is conceptually close. The distinction made (testing error versus differential privacy, spending at registration) is correct but thin.

### 4.2 The distributed contribution is weaker than the title suggests (high)
- **H-coop failed in 20 of 20 comparisons.** W independent deployments at ε/W, *each obeying R1–R4*, are just as fast and equally valid. So what the evidence supports is "execution hygiene for any parallel harness" (dedup, in-order consumption, no fresh-key retry, conservative imputation), plus "do not let workers spend ε locally."
- **The ledger and global budget mainly serve a design choice.** They are needed only if one *chooses* to share one ε across workers. That choice gave no measurable benefit, and the global-budget rule (R5) was not even shown to matter at W = 8.
- **Required.** Reframe the contribution around the rules, not around cooperation. Either drop "distributed estimation" from the title, or show a setting where a shared ledger is necessary: for example elastic membership with unknown W, or cross-team pooling of evidence.

### 4.3 Sample efficiency (high)
- **LEXIS loses to repaired Algorithm 1 by a factor of 3–6** at a matched budget. A practitioner would rationally choose repaired Algorithm 1, run on a harness that follows R1–R4.
- **The hybrid is untested.** The paper proposes screening followed by e-process confirmation as the fix but does not test it. Without that, the paper offers a valid but inefficient estimator.
- **Required.** Implement and evaluate the hybrid. Compare it against repaired Algorithm 1 at matched budgets on both scenarios.

### 4.4 Synthetic-only evidence (high)
- **No real agents.** Every quantitative claim comes from Bernoulli oracles with assumed latency and crash models. The central practical claim, that default harnesses inflate error, needs measured values of (c₀, c₁) and redelivery rates from real agents and real queue systems.
- **Required.** Run at least protocol steps 1–2 of §9.9 before submission: fault profiling and the replay-determinism audit.

### 4.5 Strength of assumptions (medium)
- **A1 (no hidden state between episodes)** is exactly what memory-surface scenarios threaten. The paper offers only a diagnostic. It should include a test of snapshot isolation in the real harness.
- **A4 (crash independence).** Crashes caused by shared infrastructure load are plausible. Arguably, load correlates with outcomes because violating episodes are longer. The paper should quantify how badly a violation of A4 breaks validity, or require replay mode.
- **Seeded determinism of LLM serving.** It is fragile in practice (batching, GPU non-determinism). If replay mode is unavailable, async mode's conservative imputation costs power, measured at 1.7× under 20% crashes.

### 4.6 Statistical issues (medium)
- **S2 speed-up is not well identified.** At W = 1, 38% of runs are censored, so the 21.4× speed-up is a lower bound and its RMST-based estimate is horizon-dependent. Report the horizon sensitivity, or use a larger H for W = 1.
- **Power of the validity checks.** 400 seeds give limited power to detect *modest* inflation, for example 0.065 versus 0.05 in the R5 row. A "valid" verdict based on a Wilson lower bound ≤ ε is conservative toward *accepting* validity. A one-sided test of H₀: rate ≥ 0.05 would show validity more convincingly. For FRESCO the observed upper limits (≤ 0.042) already do that, but the paper should say so explicitly.
- **Common random numbers.** Seeds are shared across methods, so runs are positively correlated, yet independent-sample tests were used. This is conservative but wasteful; paired analyses would be more powerful.
- **Certificates.** Coverage of 1.000 next to median η of 0.4–0.75 shows the certificates are valid but nearly uninformative. The paper is honest about this, but it should drop certificates from the contributions list or show a regime where they are informative.

### 4.7 Baseline fairness (medium)
- **Algorithm 1 parameters** (q = 40, r_d = 5, T = 3, r_h = 30) were chosen by the authors, and LEXIS defaults were not tuned. Both choices affect E4. A sensitivity sweep over both is needed before the efficiency verdict is final.
- **Missing scheduler baseline.** No ASHA or successive-halving baseline was implemented, although it is the most natural parallel-search comparator.
- **Uncorrected levels in the original specification.** Correcting across levels is what the "faithful" Algorithm 1 lacks. The manuscript should quote the original text verbatim, so readers can check that "as specified" is a fair reading of "a predefined multiplicity rule."

## 5. Minor concerns
1. Theorem numbering differs between the Stage 2 notes and the manuscript (Theorems 8/9 versus 5/6). This is harmless, but the supplementary material should be aligned.
2. The coordination cost is measured in virtual time. Real ledger CPU and database latency are not measured.
3. Figure 9 has a start-up spike at t = 0 that should be explained or trimmed.
4. "Reaches the true margin" for LEXIS means b̂ = k*, while LEXIS may confirm level 4 first and continue. State this clearly in the efficiency definition.
5. References: several 2026 items (AgentLAB, CausalTrace, AgentBoundary, Mastermind, the evidential-ceilings paper) are very recent. Re-verify venues and page numbers at submission time.
6. The abstract is about 270 words. Check the target journal's limit; many Springer journals cap abstracts at 150–250 words, so it will probably need cutting.

## 6. Unsupported or over-reaching claims to remove or qualify
- Any phrase implying that real harnesses *do* inflate error: say *can* until §9.9 data exist.
- "Negligible coordination cost": qualify with "in virtual time, at agent-episode durations".
- "Fault-tolerant": qualify as crash-stop and partition-tolerant, *not* Byzantine.
- Certificates must never be described as robustness evidence.

## 7. Ethical and dual-use review
- **Dual use.** The work measures the cost of attacking agents. The artifact contains no attack payloads and uses synthetic oracles only, so the risk is low.
- **Real-agent runs.** These must keep sandboxed mock tools and follow responsible disclosure for any real-system vulnerability (as in the MARGIN-Bench ethics section).
- **AI-assistance disclosure.** This is mandatory, and the manuscript flags it as a placeholder.

## 8. Publication readiness checklist
| Item | Status |
|---|---|
| Original, defensible contribution stated without over-claiming | partly; needs reframing (§4.2) |
| Proofs correct | yes (reviewed); depth limited |
| Real evidence for the practical claim | **missing** |
| Competitive efficiency or clear positioning | **missing** (hybrid untested) |
| Fair, tuned baselines | partly |
| Reproducibility package | strong |
| References verified | yes, as of Oct 2026; re-check at submission |
| Declarations, authorship, AI disclosure | placeholders |
| Template | standard article; port to sn-jnl v3.1 before submission |

## 9. Recommended redesign (in priority order)
1. **Reframe.** Make the paper about *validity of statistical security evaluation under distributed execution*: the rules, necessity, and real-harness measurements. Treat the global ledger as one implementation, not as the contribution. Candidate title: *"Execution Semantics Are Statistics: Valid Sequential Security Evaluation of LLM Agents on Unreliable Infrastructure."*
2. **Measure.** Run real-agent fault profiling and the replay audit on two open-weight models and one queue technology. Report the measured inflation of each default. This single experiment decides the paper's significance.
3. **Fix efficiency.** Implement screening followed by e-process confirmation with scouting-weighted spending, and compare it against repaired Algorithm 1 under a parameter sweep.
4. **Tighten statistics.** Use paired analyses for common-random-number runs, a horizon-sensitivity check, and one-sided validity tests.
5. **Consider merging.** Fold the corrected estimator and the execution rules into the MARGIN-Bench paper as its estimation section. That may be a stronger single publication than two thinner ones.

## 10. Overall assessment
The work is careful, honest, and reproducible. Its negative results are reported rather than hidden, and it found a real error in the benchmark it set out to extend. It is not yet a high-impact research article. The theory is standard, the distributed algorithm offers no advantage over correctly executed independent runs, and the practical claim lacks real-world measurement. After the redesign above it could be a solid contribution to a security-evaluation or dependable-systems venue.
