# Stage 6 — Screening + LEXIS Hybrid (LEXIS-S)

This follow-up responds to peer-review concern §4.3: LEXIS was 3–6× less sample-efficient than repaired Algorithm 1. It does three things:
1. **Design** of LEXIS-S, a screening + e-process hybrid.
2. **Validity argument**: why the hybrid keeps the guarantees of the earlier stages.
3. **Preregistered evaluation**: the hypotheses, committed before any run, and the results, added afterwards in §5.

All evidence is **[SYNTHETIC]**: slot-level single-process runs on the same reservoir instances as E4.

---

## 1. Design

### 1.1 Algorithm LEXIS-S
The levels are processed in ascending cost order, as in Algorithm 1. Pass n gets error budget A_n = ε/(n(n+1)); single-pass mode uses only n = 1. For each level k < b̂, in pass n:

1. **Screen.** Draw q candidates. Run each for r_d trials, using keys from a separate *scouting* namespace (`PRF(κ, "scout", …)`). Scouting outcomes are never evidence.
2. **Promote.** Promote the top T candidates by scouting hits. For each promoted candidate i, fix at promotion:
   - **error weight** a_i = (A_n / K) · w_i / Σ_T w. Here w_i = h_i + 1 in scout-weighted mode (h_i = scouting hits), or w_i = 1 in uniform mode. This is weighted Bonferroni with weights taken from independent data (Genovese et al., 2006).
   - **bet prior**: pseudo-counts (ρ h_i, ρ (r_d − h_i)), with shrinkage ρ = 0.5 against winner's-curse optimism. The plug-in Kelly bet then updates on confirmation outcomes only.
3. **Confirm.** Run the betting e-process on fresh confirmation keys for up to `cap` trials. Stop at once on crossing 1/a_i, or at the cap.
4. **Stop the level.** On the first confirmation at level k, set b̂ = k and stop scanning levels ≥ k. In multi-pass mode, later passes revisit only levels < b̂, and only while budget remains.

### 1.2 Validity — follows from Theorem 1, nothing new needed
- **Weight and bet are fixed before confirmation.** Both are functions of registration information: scouting outcomes, which use keys independent of the confirmation keys. They are therefore 𝓡_i-measurable, as Theorem 1 requires.
- **Bets stay predictable.** Confirmation bets depend on the registration information and the committed prefix only.
- **Total budget ≤ ε.** Σ_i a_i ≤ Σ_n A_n ≤ ε. Each pass splits A_n into A_n/K per level, and that share is divided over the T promoted candidates.
- **Selection does not break it.** Choosing which candidates to promote from scouting data is just adaptive candidate generation, which Theorem 1 allows.
- **Distributed setting.** In FRESCO, scouting slots go in their own namespace and promotion is a REGISTER carrying the scouting-derived weight. All six rules apply unchanged.

### 1.3 Comparator: multi-pass repaired Algorithm 1
To compare like with like in anytime mode, Algorithm 1 is also given passes. Pass n tests each of its K·T confirmations at the Clopper–Pearson level ε/(n(n+1)·K·T), so the total error is again ≤ ε.

---

## 2. Preregistered hypotheses (committed before any LEXIS-S run)

**Setup.**
- Instances: S1-moderate, S2-sparse and boundary-null, identical to E4. α = 0.2, ε = 0.05.
- 2,000 runs per cell.
- Default parameters, shared by both methods: q = 40, r_d = 5, T = 3, cap = r_h = 30.

| ID | Hypothesis | Criterion | Comparator |
|---|---|---|---|
| H6-valid | LEXIS-S is valid | Wilson lower bound of P(false confirmation) ≤ 0.05 on the boundary null, for every variant | — |
| H6-noninf | Single pass: LEXIS-S reaches k* at least as often as repaired Algorithm 1 | lower bound of the 95% CI of the difference P_hyb − P_alg1 > −0.05 (non-inferiority margin 0.05), on S1 and S2 | repaired Algorithm 1, same parameters |
| H6-cheaper | Single pass: LEXIS-S uses fewer oracle calls | mean slots per run lower, with the 95% bootstrap CI of the ratio below 1, on S1 and S2 | same |
| H6-anytime | With a 5,000-call budget, multi-pass LEXIS-S reaches k* at least as often as multi-pass repaired Algorithm 1 | as in H6-noninf | multi-pass Algorithm 1 |
| H6-weights | Scout-weighted spending and bet priors beat uniform weights with an uninformed prior | difference in P(reach k*) > 0, with the CI excluding 0, on at least one instance | LEXIS-S uniform |
| H6-sens | Conclusions about H6-noninf hold across a parameter sweep (q, r_d, T) ∈ {(20,5,3), (40,3,3), (80,5,5)} | H6-noninf criterion at every setting | repaired Algorithm 1 at the same setting |

Holm correction is **not** applied to non-inferiority, since each hypothesis is judged separately. All failures will be reported.

---

## 3. Results [SYNTHETIC] (added after the runs)
**Scale.** 60,000 runs: 2,000 per cell, 30 cells, 31 s on 4 cores. Script: `experiments/e8_hybrid.py`. All tables: `results/processed/summary.md`, section E8.

### 3.1 Headline numbers (default parameters (40, 5, 3); P(reach k*) with 95% Wilson CI)
| Method | S1-moderate | S2-sparse | Mean calls S1 / S2 | P(false) on boundary null |
|---|---|---|---|---|
| LEXIS (Stage 4, matched budget) | 0.246 | 0.043 | — | 0.018 |
| **LEXIS-S** (single pass) | **0.756** [0.737, 0.775] | **0.251** [0.232, 0.270] | 872 / 1,031 | **0.004** [0.002, 0.008] |
| LEXIS-S, uniform weights | 0.756 [0.737, 0.775] | 0.231 [0.213, 0.250] | 875 / 1,039 | 0.004 |
| Repaired Algorithm 1 (single pass) | 0.808 [0.790, 0.825] | 0.269 [0.250, 0.289] | 868 / 1,034 | 0.034 [0.027, 0.043] |
| LEXIS-S, multi-pass (5,000 calls) | 0.998 | 0.733 [0.713, 0.751] | 1,141 / 2,893 | 0.014 |
| Repaired Algorithm 1, multi-pass | 1.000 | 0.765 [0.746, 0.783] | 1,088 / 2,781 | 0.015 |

### 3.2 Verdicts
| Hypothesis | Result | Verdict |
|---|---|---|
| H6-valid | every LEXIS-S variant ≤ 0.014 (upper limit ≤ 0.021) at the boundary null | **supported** |
| H6-noninf | difference in P(reach k*), LEXIS-S − Algorithm 1: S1 −0.052 [−0.077, −0.026]; S2 −0.018 [−0.045, +0.009] | **not supported** on S1 (inferiority not excluded); non-inferior on S2 |
| H6-cheaper | mean-calls ratio 1.005 [0.995, 1.014] (S1) and 0.998 [0.989, 1.006] (S2) | **refuted**: no saving |
| H6-anytime | multi-pass difference: S1 −0.002 [−0.005, +0.001]; S2 −0.032 [−0.059, −0.006] | non-inferior on S1; **not** on S2 |
| H6-weights | scout vs uniform: S1 +0.000 [−0.027, +0.027]; S2 +0.020 [−0.007, +0.046] | **not supported** |
| H6-sens | sweep settings (20,5,3), (40,3,3), (80,5,5): differences −0.020 to −0.049; non-inferior in 2 of 6 | **not supported**: conclusion is not robust in LEXIS-S's favour |

### 3.3 Interpretation
1. **Screening was the missing piece.** Adding Algorithm 1's screening stage to LEXIS lifts P(reach k*) from 0.246 to 0.756 on S1 and from 0.043 to 0.251 on S2. This removes most of the 3–6× gap found in Stage 4. The cause was search structure, not the statistics of confirmation.
2. **The remaining 2–5 point gap is the price of anytime validity.** A fixed-n exact Clopper–Pearson test at n = 30 uses its error budget fully: its false-confirmation rate is 0.034 against a nominal 0.05. A betting e-process capped at 30 trials is valid at every stopping time, so it is more conservative at any fixed n (0.004). The spare error budget is exactly the power it gives up.
3. **Early stopping saves almost nothing here.** About 800 of roughly 870 calls go to screening. Confirmation is a small share of the cost, so sequential confirmation cannot reduce total calls. That is why H6-cheaper fails.
4. **Scouting-weighted spending did not help.** Promoted candidates have similar scouting scores (top 3 of 40), so the weights are nearly uniform.
5. **Consequence for the project.** The e-process confirmation buys three properties:
   - continuation and multi-pass extension without pre-planning;
   - validity under arbitrary stopping;
   - a natural fit to asynchronous, in-order evidence streams.

   It does **not** buy sample efficiency. The FRESCO execution rules (R1, R3, R4, R5) apply equally to fixed-n confirmations. A fixed-n test also needs exactly-once slots, no fresh-key retries, and a global error budget. In-order commit is replaced by its fixed-sample counterpart: the evidence must be a slot set fixed in advance, never "the first n results to arrive". Experiment E9 (added during the reframing) shows that arrival-selected evidence breaks a fixed-n test almost surely (0.999). **So the strongest practical recommendation is: repaired Algorithm 1 (or LEXIS-S, where anytime properties matter), executed under the FRESCO rules.** This supports the peer review's reframing (§4.2 there): the contribution is the execution rules and the estimator repair, not a new, more efficient estimator.

### 3.4 What was not tried (to avoid post-hoc tuning)
- larger caps for LEXIS-S, which would spend more calls;
- mixture or prior-free bets other than the plug-in;
- adaptive allocation of confirmation trials between promoted candidates.

Any of these may close the remaining gap. Each would need its own preregistration.
