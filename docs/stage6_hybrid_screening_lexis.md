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

## 3. Results
*(Added after the runs. See §5.)*
