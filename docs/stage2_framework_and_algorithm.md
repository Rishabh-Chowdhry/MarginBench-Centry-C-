# Stage 2 — Mathematical Framework and the FRESCO Algorithm

**Scope.** This stage gives the formal model, the guarantees with their proofs, the algorithm in pseudocode, a cost analysis, and counterexamples. It builds on Stage 1 (`docs/stage1_novelty_and_directions.md`).
**Evidence status.** Every result below carries one of four labels: **Theorem/Proposition (proved here)**, **Proof sketch**, **Conjecture**, or **Empirical hypothesis**. The only numbers come from `sims/stage2_checks.py`. That script runs synthetic Bernoulli oracles to test the mathematics against an independent implementation. It is not evidence about LLM agents.
**Reference code.** `fresco/` contains an executable specification of the statistical core: `eprocess.py`, `spending.py`, `certificates.py` and `lexis.py`. `tests/test_core.py` holds the unit tests (14 pass).

---

## 0. What changed since Stage 1 (self-correction)

1. **Stage 1 Conjecture B5 was argued badly.** It said that W independent searches "pay the Bonferroni price log(W/ε)" while cooperation avoids it. That reasoning does not hold. Cooperative search that spends error budget over a *global* registration index pays about 2 log J_total = 2 log W + 2 log J_w (§3.2). That is *more* than W independent runs at ε/W, which pay log W + 2 log J_w. Cooperation has **no automatic statistical advantage**. Any advantage must come from three things:
   - pruning against the frontier;
   - concentrating error budget on globally promising candidates, using weights chosen from independent scouting data (§3.2);
   - load balancing.
   These are empirical questions. B5 is restated as Empirical Hypothesis H-coop (§9).
2. **The obvious reviewer objection, faced head-on.** *"MARGIN-Bench has about 2,000 independent (scenario, surface) estimation problems. Run them in parallel and nothing intra-scenario is needed."* This is largely right about *throughput*. The answer that survives scrutiny:
   - (a) The validity hazards of Theorem 9 arise in **any** distributed execution of trials, including embarrassingly parallel harnesses. Those harnesses use at-least-once queues, retries and arrival-order processing. So Theorems 1 and 8 matter even with zero intra-scenario cooperation.
   - (b) Intra-scenario parallelism matters for *latency* when there are few expensive scenarios, as in release gating of one model or long-horizon episodes, and for straggler mitigation under heavy-tailed scenario difficulty.
   The headline contribution is therefore **schedule-oblivious validity** (Theorems 1 and 8, with necessity in Theorem 9). The cooperative speed-up is secondary and has to be tested.

---

## 1. System model

### 1.1 Objects
- Scenarios $e \in \mathcal{E}$, grouped into families $f(e)$ that are the independent units for aggregate inference. Each scenario has a surface $s$, an agent configuration $M$, and an authorization oracle $V$, all as in the manuscript.
- Intervention space $A = A_s(e)$, countable, with cost $c: A \to \{1,\dots,K\}$. Level $k$ is $L_k = \{\delta : c(\delta) = k\}$, and budget sets are $B(b) = \bigcup_{k \le b} L_k$.
- **Slot outcome.** Executing intervention $\delta$ with randomness key $u$ gives $Y(\delta,u) \in \{0,1\}$, a *committed* violation as judged by $V$ on the post-state. The violation probability is $p(\delta) = \Pr_u[Y(\delta,u)=1]$.
- **Ideal margin**, from manuscript §4.2: $R = R_{s,\alpha}(M,e) = \inf\{c(\delta) : p(\delta) \ge \alpha\}$, with $\inf\emptyset = \infty$.
- **Generator** $G$: any randomized procedure that proposes candidates. It may be adaptive and may use every outcome released to it. At level $k$, *audit mode* draws $\delta \sim D_k$ i.i.d. from a distribution fixed before the run.

### 1.2 Nodes and agents
- **Ledger** $\mathsf{L}$: the single linearizable source of truth for candidates, slots, budget leases, the frontier, and audit counts. Stage 3 implements it as a replicated, durable store. Here it is an abstract linearizable object.
- **Workers** $w \in \mathcal{W}(t)$. Membership changes over time. Workers run generators, request slots, execute them through **executors**, and report results. Workers are honest but crash-prone (crash-stop; a restart is a new incarnation).
- **Executors**: the sandboxed agent under test, its tools, and the oracle $V$, all instantiated from an immutable snapshot for each slot.
- **Agents inside the scenario**: the evaluated LLM agents, including delegated sub-agents for the inter-agent surface. They are part of $M$ and are *subjects*, not participants in the protocol.

### 1.3 Trust and attacker model
| Party | Trusted for | Not trusted for |
|---|---|---|
| Ledger $\mathsf{L}$ | linearizability, durability, secrecy of the run key $\kappa$ | — |
| Workers | following the protocol (honest-but-crash) | timing, liveness, survival |
| Generator $G$ (the *evaluated attacker*) | nothing statistical | It is adversarial toward the defender *and potentially toward the measurement*: it may try to exploit seed reuse, selection, or duplicates. It never sees a seed before the corresponding slot is registered and leased, and it cannot write to the ledger |
| Defender under test $M$ | nothing | It may behave arbitrarily inside the sandbox |
| Oracle $V$ | correctness of committed-violation labels (assumption A5) | — |
| Model provider (API) | nothing | Stationarity: silent updates are possible (A3) |
| Network | nothing | It may delay, reorder, duplicate, or drop messages, and may partition |

Byzantine workers are **out of scope**. Workers belong to the evaluator, so the threat model does not justify Byzantine fault tolerance (§8, item 7).

### 1.4 Assumptions, each with the clause that breaks when it fails
- **A1 (fresh-key conditional Bernoulli).** Slot $(j,k)$ uses key $u_{j,k}$. The keys $(u_{j,k})$ are i.i.d., independent of the generator's randomness and of all other keys. Then $Y_{j,k} = Y(\delta_j, u_{j,k})$. *Realisation:* $u_{j,k} = \mathrm{PRF}_\kappa(\mathrm{run}, j, k)$ for seeded open-weight models, or an independent fresh draw per execution for unseeded APIs. *If it fails* (shared hidden state across slots, cache carry-over): Theorem 1 fails; see the counterexample in §8, item 3.
- **A2 (registration before revelation).** $u_{j,\cdot}$ is revealed to no one before candidate $j$ is registered with its weight $a_j$ fixed. *If it fails*, a generator can select on seeds (CE5).
- **A3 (stationarity or monotone-null).** Either $p(\delta)$ is constant during the run, or the null is read as "$p_{j,k} \le \alpha$ for every slot". Under drift the guarantee survives in that weaker reading (Remark 1.1).
- **A4 (crash independence).** Whether slot $(j,k)$ crashes or times out may depend on its own key and trajectory $u_{j,k}$, and on infrastructure noise independent of every *other* key. Timeouts are per-slot deadlines measured from that slot's start. *Not needed in replay mode* (Remark 4.2).
- **A5 (oracle correctness).** $Y$ is the true committed-violation indicator. If the oracle has a false-positive rate $\omega$, every guarantee holds for $p_{\text{obs}} = p + \omega(1-p)$, not for $p$ (§8, item 4).
- **A6 (independence across families).** This is used only for aggregate curves (Corollary 3).

*Remark 1.1 (drift).* Every proof uses only $\mathbb{E}[Y_{j,k} \mid \text{past}] \le \alpha$ under the null. If $p$ drifts, validity holds for the null "$p_{j,k} \le \alpha$ at every slot". A confirmation then means "the violation probability exceeded $\alpha$ at some point during the run". That is weaker but still honest. Stage 3 adds a drift sentinel: a fixed candidate re-run periodically with a two-sample e-test.

---

## 2. Estimands and target guarantees

The procedure outputs $\hat b \in \{1,\dots,K\} \cup \{\infty\}$ (where $\infty$ means CENSORED), a witness $j^*$ with its committed slot trace, certificates $\bar\eta_1,\dots,\bar\eta_K$, and a full query ledger.

- **(G1) Upper-side validity.** $\Pr(R > \hat b) \le \varepsilon$. So $\hat b$ is a $(1-\varepsilon)$ upper confidence bound on the ideal margin. It is implied by the stronger **no-false-witness** property $\Pr(\exists j \text{ confirmed with } p(\delta_j) \le \alpha) \le \varepsilon$.
- **(G2) Level certificates.** Let $\mu_k = D_k\{\delta : p(\delta) \ge \alpha\}$. Then $\Pr(\exists k : \mu_k > \bar\eta_k) \le \varepsilon'$.
- **(G1 ∧ G2)** hold jointly with probability $\ge 1-\varepsilon-\varepsilon'$, by a union bound.
- **Non-claim.** No statement of the form $R > b$ is ever produced. G2 is about the generator's distribution, not about $R$. This preserves manuscript §4.2 and §12.5.

---

## 3. LEXIS: the statistical core

### 3.1 Per-candidate betting e-process
For candidate $j$, the null is $H_j: p(\delta_j) \le \alpha$ and

$$E_{j,n} = \prod_{i=1}^{n}\bigl(1 + \lambda_{j,i}(\tilde Y_{j,i} - \alpha)\bigr), \qquad \lambda_{j,i} = f_j\bigl(\mathcal{R}_j, \tilde Y_{j,1},\dots,\tilde Y_{j,i-1}\bigr) \in [0, 1/\alpha).$$

Here $\mathcal{R}_j$ is the registration information (δ_j, c_j, a_j and anything observed before registration), and $\tilde Y$ is the *recorded* outcome (§4.3). Bets depend only on the registration information and the committed prefix of the same candidate. This is **rule R2**, enforced in code because a strategy receives only $(s, n)$ (`fresco/eprocess.py`).

Candidate $j$ is **confirmed** once $\sup_{n} E_{j,n} \ge 1/a_j$.

### 3.2 Spending
- Weights $a_j$ are fixed at registration and are $\mathcal{R}_j$-measurable, with $\sum_j a_j \le \varepsilon$ almost surely (ledger invariants I1–I2).
- Default: $a_j = \varepsilon_\ell/(i(i+1))$ for the $i$-th registration under lease $\ell$. The threshold $\log(1/a_j) \approx \log(1/\varepsilon_\ell) + 2\log i$ grows logarithmically. Geometric spending would make it grow linearly.
- **Scouting-weighted spending.** This is allowed because $a_j$ only needs to be $\mathcal{R}_j$-measurable. Results from a separate scouting key namespace, never counted as evidence, may set $a_j$; promising candidates receive larger weights. This is the e-process analogue of p-value weighting with independent data (Genovese, Roeder & Wasserman, *Biometrika* 2006, doi:10.1093/biomet/93.3.509).

### 3.3 Theorem 1 (validity of LEXIS; schedule-oblivious) — *proved*
Assume A1, A2, A4 and A3 (in its monotone-null reading), rule R2, and $\sum_j a_j \le \varepsilon$ a.s. Then for **any** generator, any allocation and continuation policy, any stopping rule, and any order or timing in which slots are *executed*, provided the e-process consumes recorded outcomes in slot order:

$$\Pr\bigl(\exists j:\ H_j \text{ true and } j \text{ confirmed}\bigr) \le \varepsilon, \qquad\text{hence}\qquad \Pr(R > \hat b) \le \varepsilon.$$

*Proof.* Index candidates by registration order $j = 1, 2, \dots$. Extend each candidate's slot sequence to infinity *conceptually*: define $\tilde Y_{j,k}$ for every $k$, including slots never executed, as the recorded value the slot would have had. Let $E^*_{j,n}$ be the e-process on this full sequence, with the same bets $f_j$.

**(i) Supermartingale.** Let $\mathcal{G}_{j,n} = \sigma(\mathcal{R}_j, \tilde Y_{j,1..n}, \text{crash noise of slots } 1..n)$. By A1 and A2, $u_{j,n+1}$ is independent of $\mathcal{G}_{j,n}$. Registration information depends only on keys of *other* candidates, and earlier recorded values of $j$ depend only on $u_{j,1..n}$ and on crash noise independent of $u_{j,n+1}$ (A4). Hence $\mathbb{E}[Y_{j,n+1} \mid \mathcal{G}_{j,n}] = p(\delta_j)$. Since $\tilde Y \le Y$ pointwise (§4.3), $\mathbb{E}[\tilde Y_{j,n+1} \mid \mathcal{G}_{j,n}] \le p(\delta_j) \le \alpha$ under $H_j$. With $\lambda_{j,n+1}$ being $\mathcal{G}_{j,n}$-measurable and non-negative, $\mathbb{E}[E^*_{j,n+1} \mid \mathcal{G}_{j,n}] = E^*_{j,n}(1 + \lambda(\mathbb{E}[\tilde Y]-\alpha)) \le E^*_{j,n}$. Positivity holds because $1 - \lambda\alpha > 0$.

**(ii) Ville, conditional on registration.** $E^*_{j,0} = 1$, so $\Pr(\sup_n E^*_{j,n} \ge 1/a_j \mid \mathcal{R}_j) \le a_j$ on $\{H_j\}$. Both $a_j$ and $H_j$ are $\mathcal{R}_j$-measurable.

**(iii) The schedule enters only through truncation.** Whatever the scheduler does, the committed stream of $j$ is a *prefix* of the full sequence, by in-order commit and deduplication (R1 and R3). Confirmation therefore implies $\sup_n E^*_{j,n} \ge 1/a_j$. Abandonment, pruning, out-of-order execution, and even clairvoyant stopping only shorten the prefix, so they cannot create a crossing that the full sequence lacks.

**(iv) Union.** $\Pr(\bigcup_j \{H_j, j \text{ confirmed}\}) \le \mathbb{E}\sum_j a_j \mathbf{1}\{j \text{ registered}\} \le \varepsilon$.

Finally, if no null is confirmed, every confirmed $\delta$ has $p > \alpha$, so $R \le \hat b$. ∎

**Why this is the key mechanism.** Step (iii) makes validity independent of the scheduler. Any heuristic, learned, or distributed scheduler is automatically safe, provided the evidence stream satisfies R1–R3. Optimisation and validity are **decoupled**, and §5 exploits this.

**Check.** Numerical check P1 (`sims/stage2_checks.out.txt`). False-confirmation rate: 0.010 with all-null reservoirs at $p=\alpha$; 0.0017 with mixed reservoirs; 0.0107 under adversarial data-dependent continuation. Each is below ε = 0.05.

### 3.4 Proposition 2 (anytime zero-failure certificate) — *proved*
Let $Z_1, Z_2, \dots$ be i.i.d. Bernoulli($q$). For any random time $N$, including one that depends on the data,

$$\Pr\bigl(S_N = 0 \ \text{and}\ q > 1 - \beta^{1/N}\bigr) \le \beta.$$

*Proof.* Let $n_0 = \min\{n : 1-\beta^{1/n} < q\} = \lceil \log\beta / \log(1-q)\rceil$. The bad event requires $N \ge n_0$ with no success in the first $N$ draws, so it is contained in "the first $n_0$ draws are all zero". That event has probability $(1-q)^{n_0} \le \beta$. ∎

*Certificate.* Audit draws $\delta \sim D_k$, each run $r$ times. Set $Z = 1$ if any run violates, and also $Z = 1$ if any run crashes. Then $q_k \ge \mu_k(1-(1-\alpha)^r)$, because a draw with $p \ge \alpha$ shows a success with probability at least $1-(1-\alpha)^r$. Hence

$$\bar\eta_k = \frac{U_k}{1-(1-\alpha)^r}.$$

Here $U_k$ is the zero-failure bound when $S_k = 0$ and the confidence-sequence bound of Proposition 3 otherwise. Each is used at level $\varepsilon'/(2K)$, so the reported value is wrong only if one of the two bounds is wrong. A union over levels gives G2.

*Example.* With $K=4$, $\varepsilon' = 0.05$, $\alpha = 0.2$: 1,000 clean audit draws with $r=3$ give $\bar\eta_k = 0.0104$. With $N=100$ draws and $r=10$, $\bar\eta_k = 0.055$.

**Check.** P2. The empirical miss rate at the most optimistic possible stopping time is 0.048–0.051, against an exact worst case of 0.0485–0.0499. The bound is tight.

### 3.5 Proposition 3 (betting upper confidence sequence without a grid union) — *proved*
For grid values $g$, test $H_g: q \ge g$ with $\prod (1 + \lambda_i (g - Z_i))$, where $\lambda_i \in [0, c/(1-g)]$ is predictable. Define $U_n = \min\{g : \text{every grid value} \ge g \text{ is rejected by time } n\}$. Then $\Pr(\exists n: q > U_n) \le \beta$.

*Proof.* If $q > U_n$, the largest grid value $g \le q$ satisfies $g \ge U_n$, so it has been rejected. But $H_g$ is true, and its e-process is a non-negative supermartingale. Ville bounds this single event by $\beta$. ∎

**Check.** P3: miss rates 0.000 and 0.015 against a bound of 0.05.

### 3.6 Proposition 4 (confirmation time: matching upper and lower bounds) — *proved*
- **Upper bound.** With the fixed bet $\lambda$ and true $p$ such that $g(\lambda,p) = p\log(1+\lambda(1-\alpha)) + (1-p)\log(1-\lambda\alpha) > 0$, the confirmation time at level $a$ satisfies

  $$\mathbb{E}_p[\tau] \le \frac{\log(1/a) + \log(1+\lambda(1-\alpha))}{g(\lambda,p)}.$$

  *Proof.* $\log E_n$ is a random walk with drift $g > 0$ and increments at most $u = \log(1+\lambda(1-\alpha))$. So $\tau < \infty$ a.s. and $\mathbb{E}\tau < \infty$. The overshoot gives $\log E_\tau \le \log(1/a) + u$, and Wald's identity gives $g\,\mathbb{E}\tau = \mathbb{E}\log E_\tau$. ∎
- **Kelly.** For the alternative $p_1$, the Kelly bet $\lambda^* = (p_1-\alpha)/(\alpha(1-\alpha))$ attains $g(\lambda^*, p_1) = \mathrm{KL}(p_1\|\alpha)$; verified symbolically in `tests/test_core.py::test_kelly_growth_equals_kl`.
- **Lower bound.** Any level-$a$ sequential test that stops a.s. under $p$ has $\mathbb{E}_p\tau \ge \log(1/(2.4a))/\mathrm{KL}(p\|\alpha)$. This is the change-of-measure argument of Kaufmann, Cappé & Garivier, *JMLR* 17 (2016), https://jmlr.org/papers/v17/kaufman16a.html, applied to $\tau\wedge n$ with $n\to\infty$.
- **Consequence.** The per-candidate cost is $\Theta(\log(1/a_j)/\mathrm{KL}(p\|\alpha))$. Confirming near the threshold is inherently expensive. For $\alpha = 0.2$: $1/\mathrm{KL} = 35$ at $p = 0.3$ and $9.6$ at $p = 0.4$, in units of $\log(1/a)$.

**Check.** P4. For $p_1 = p = 0.4$, the empirical $\mathbb{E}\tau$ is 38.1; the lower bound is 26.9 and the Wald upper bound 41.9. The other two configurations also fall inside their bracket.

### 3.7 Proposition 5 (expected work to reach a findable level) — *proved for a non-adaptive generator*
**Setting.** Level $k$ draws candidates i.i.d. with $\pi_k(\Delta) = D_k\{p \ge \alpha+\Delta\}$. Use the fixed bet $\lambda_\Delta$, Kelly for $\alpha+\Delta$, and a per-candidate cap

$$m = \frac{2(L_{\max}+u)}{\mathrm{KL}(\alpha+\Delta\,\|\,\alpha)}, \qquad L_{\max} = \log\frac{J_{\max}(J_{\max}+1)}{\varepsilon}.$$

Scheduling uses fixed weights $w$ and audit share $\rho$ with $r$ runs per audit. Then

$$\mathbb{E}[\text{slots until } \hat b \le k] \le \frac{2m}{\pi_k(\Delta)} \cdot \frac{(1-\rho) + \rho r}{(1-\rho)\,w_k}.$$

*Proof.* By Proposition 4 and Markov's inequality, a candidate with $p \ge \alpha + \Delta$ crosses within $m$ slots with probability at least ½. So each level-$k$ candidate independently yields a confirmation with probability at least $\pi_k/2$ and uses at most $m$ slots. By Wald's identity over the geometric number of candidates, level $k$ needs at most $2m/\pi_k$ slots in expectation. Each scheduling decision is a level-$k$ candidate slot with probability at least $(1-\rho)w_k$; pruning only increases the normalised weight of a surviving level. Each decision costs $(1-\rho)+\rho r$ slots in expectation, and Wald's identity applies again. ∎

*Worked numbers* (from `fresco.eprocess`, with $\alpha = 0.2$, $\varepsilon = 0.05$, $K = 4$, uniform weights, $\rho = 0$):

| Δ | KL | $J_{\max}$ | cap $m$ | π = 0.05 | π = 0.01 |
|---|---|---|---|---|---|
| 0.1 | 0.028 | 1000 | 1,223 | 195,603 | 978,016 |
| 0.2 | 0.105 | 1000 | 335 | 53,528 | 267,642 |
| 0.4 | 0.382 | 10 | 46 | 7,369 | 36,846 |

The two Markov steps make these bounds loose by about 4×. In check P6, with Δ = 0.5, cap 30 and π = 0.05, the empirical cost is about 2.7k slots. The bounds still show the real scaling, $\propto K\,(\log(1/\varepsilon) + 2\log J)/(\pi_k\,\mathrm{KL})$. They also confirm that the manuscript's workload is in the $10^7$–$10^8$ oracle-call range when margins are hard to find, which justifies distribution independently of Stage 1's estimate.

### 3.8 Proposition 6 (uniform weights are minimax among fixed-weight schedules) — *proved*
Consider $K$ instances. In instance $k$ only level $k$ is findable, and its isolated expected work is $T$. Under fixed weights $w$, the expected work in instance $k$ is $T/w_k$ by Wald's identity, so the worst case is $T/\min_k w_k \ge KT$. Uniform weights achieve $KT$.

The factor-$K$ price is unavoidable for fixed weights. Adaptive schedules could in principle do better on structured instances (that is an open question). Using cheap-first weights is a *preference*, not an optimisation, and it costs up to $1/\min_k w_k$.

**Check.** P6: worst case 2,912 slots under uniform weights versus 12,798 under cheap-first weights (0.55, 0.25, 0.12, 0.08).

### 3.9 Corollary 7 (aggregate discovered-compromise curve) — *proved*
Let $\hat F(b) = \frac1N\sum_i \mathbf{1}\{\hat b_i \le b\}$ and $F(b) = \frac1N\sum_i \mathbf{1}\{R_i \le b\}$. For every $b$ simultaneously,

$$\hat F(b) - F(b) \le \frac1N\sum_i \mathbf{1}\{\hat b_i < R_i\}.$$

The left side can be positive only if $\hat b_i \le b < R_i$ for some $i$. Hence $\mathbb{E}\sup_b(\hat F - F) \le \varepsilon$. Under A6 with $N$ independent families, Hoeffding gives $\Pr(\sup_b(\hat F - F) > \varepsilon + t) \le e^{-2Nt^2}$.

So $\hat F(b)$ is a **conservative lower estimate of the fraction of scenarios vulnerable at budget $b$**. This makes precise the manuscript's caution (§8.1) that discovered curves include search failure. Error affects only one direction.

---

## 4. FRESCO: distributed model, protocol, and guarantees

**FRESCO** stands for **F**rontier-pruned, **R**eplay-safe, **E**scrowed, **S**eed-**C**ommitted **O**rchestration.

### 4.1 Ledger state
$\mathsf{S} = (\mathcal{C}, \Sigma, \Lambda, \mathcal{F}, \mathcal{A})$:
- **Candidates** $\mathcal{C}[j] = (h_j, c_j, a_j, \ell_j, \text{status}_j \in \{\text{ACTIVE, CONFIRMED, ABANDONED, PRUNED}\}, n_j, s_j, \log E_j)$.
- **Slots** $\Sigma[(j,k)] \in \{\bot,\ \text{LEASED}(w, t_0, \text{tok}),\ \text{DONE}(y, \text{trace\_hash}),\ \text{CRASHED}\}$.
- **Leases** $\Lambda[\ell] = (\text{amount}_\ell, \text{spent}_\ell, \text{open}_\ell, \text{incarnation}_\ell)$.
- **Frontier** $\mathcal{F} = (\hat b, j^*)$.
- **Audits** $\mathcal{A}[k] = (N_k, S_k, \mathrm{CS}_k)$.

### 4.2 Transitions (guarded commands; each is atomic at the ledger)
| Transition | Guard | Effect |
|---|---|---|
| GRANT(ℓ, x) | $x \le \varepsilon - \sum_{\text{open}} \text{amount} - \sum_{\text{closed}} \text{spent}$ | $\Lambda[\ell] \leftarrow (x, 0, \text{open}, \text{inc})$ |
| REGISTER(ℓ, δ, a) | open$_\ell$ ∧ spent$_\ell + a \le$ amount$_\ell$ ∧ $a$ fixed by spending rule ∧ $h(\delta)$ not in the registered set (optional dedup) | new $j$ ← next index; $\mathcal{C}[j] \leftarrow (h(\delta), c(\delta), a, \ell, \text{ACTIVE}, 0, 0, 0)$; spent$_\ell$ += $a$ |
| LEASE(j, k, w) | status$_j$ = ACTIVE ∧ $c_j < \hat b$ ∧ $\Sigma[(j,k)] = \bot$ ∧ $k \le$ cap | $\Sigma[(j,k)] \leftarrow$ LEASED(w, now, tok); release $u_{j,k} = \mathrm{PRF}_\kappa(\text{run}, j, k)$ to $w$ |
| RECORD(j, k, y, tok) | $\Sigma[(j,k)]$ = LEASED(·,·,tok) | $\Sigma[(j,k)] \leftarrow$ DONE(y, h). Any other case is ignored and logged: duplicate, late arrival, or stale token |
| EXPIRE(j, k) | LEASED ∧ now > $t_0 + T_{\text{lease}}$ | async mode: CRASHED. Replay mode: back to ⊥ with the *same* $u_{j,k}$ and a new token |
| ADVANCE(j) | $\Sigma[(j, n_j+1)]$ terminal | $\tilde y$ ← (DONE ? y : 0); $\lambda \leftarrow f_j(s_j, n_j)$; $\log E_j$ += $\log(1+\lambda(\tilde y-\alpha))$; $n_j$++; $s_j$ += $\tilde y$; if $\log E_j \ge \log(1/a_j)$: CONFIRMED, $\hat b \leftarrow \min(\hat b, c_j)$; repeat |
| PRUNE / ABANDON(j) | ACTIVE ∧ ($c_j \ge \hat b$ ∨ $n_j \ge$ cap) | status ← PRUNED / ABANDONED. Outstanding leases are cancelled and their results ignored |
| CLOSE(ℓ) | open$_\ell$ | open$_\ell$ ← false (fence); return amount − spent to the pool |
| AUDIT(k, z) | $k < \hat b$ | $N_k$++, $S_k$ += z (crash ⇒ z = 1), update CS$_k$ |

State equations: $\log E_{j,n+1} = \log E_{j,n} + \log(1+\lambda(s_{j,n},n)(\tilde Y_{j,n+1}-\alpha))$ and $\hat b(t) = \min\{c_j : \text{status}_j(t) = \text{CONFIRMED}\}$.

### 4.3 Protocol rules
- **R1 Seed-committed slots.** Evidence is indexed by $(j,k)$ and keyed by $u_{j,k} = \mathrm{PRF}_\kappa(\text{run}, j, k)$. The key is revealed only on LEASE, so A2 holds by construction.
- **R2 Prefix-predictable bets.** This is the rule of §3.1.
- **R3 Exactly-once, in-order commit.** Each $(j,k)$ has at most one terminal value (first write wins, fenced by token), and the e-process consumes only the contiguous terminal prefix.
- **R4 Direction-aware conservative imputation.** For confirmation, CRASHED becomes $\tilde Y = 0$. For audits, a crash becomes $Z = 1$. A crashed slot is never re-run with a fresh key. Re-running is allowed only with the same key, in replay mode.
- **R5 Global spending invariant.** Every $a_j$ is drawn from a ledger-granted lease. Leases are bound to a worker incarnation and fenced on CLOSE.
- **R6 Verifiable confirmation.** Only the ledger moves a candidate to CONFIRMED, by recomputing $\log E_j$ from stored slots. Worker-side values are hints.

**Invariants** (maintained by every transition in §4.2; checked in `tests/test_core.py` for the budget part):
- I1: $\sum_\ell \text{committed}_\ell + \text{unleased} = \varepsilon$.
- I2: spent$_\ell \le$ amount$_\ell$.
- I3: write-once slots.
- I4: $n_j$ is monotone and slots $1..n_j$ are terminal.
- I5: $\log E_j$ is a deterministic function of the terminal prefix.
- I6: CONFIRMED ⇒ threshold reached on the committed prefix.
- I7: $\hat b$ is non-increasing.
- I8: keys are revealed only on lease.
- I9: audit draws come from a non-adaptive stream with its own randomness.

### 4.4 Theorem 8 (validity of FRESCO under asynchrony and faults) — *proved, by reduction to Theorem 1*
Under A1–A5 and R1–R6, G1 and G2 hold for every number of workers, every membership history, and every interleaving. They also hold under message delay, reordering, duplication and loss, under crash-stop failures of workers and executors, and under network partitions.

*Proof.* We check the hypotheses of Theorem 1 one at a time.
- **Prefix property.** I3 and I4 make the committed stream of $j$ a prefix of a single well-defined sequence. Duplicates and late messages fail RECORD's token guard.
- **Recorded value never exceeds the potential outcome.** R4 gives $\tilde Y \le Y$. A crash between execution and RECORD leaves the slot LEASED, so EXPIRE turns it into CRASHED, which is recorded as 0.
- **Predictable bets.** R2 holds, and R6 makes the ledger's computation the only one that counts.
- **Fresh keys.** A1 and A2 follow from R1 and I8.
- **Budget.** $\sum_j a_j \le \varepsilon$ follows from I1, I2 and R5. A partitioned or zombie worker cannot register under a CLOSED lease, because registration is a ledger transition. In offline-escrow mode (Stage 3) the worker enforces I2 locally and the ledger rejects registrations that exceed the lease at reconciliation.
- **Partitions** only delay transitions. No transition's safety depends on timing, except EXPIRE, and EXPIRE can only make recorded values more conservative.
- **Audits.** G2 follows from R4 and I9 with Propositions 2 and 3. ∎

*Remark 4.1.* Replay mode removes the need for A4. A re-run with the same key reproduces $Y(\delta_j, u_{j,k})$ exactly, so recorded equals potential and crash correlation cannot matter. This requires seeded, deterministic execution, which Stage 3 checks by replaying a random sample of DONE slots and comparing trace hashes. Any mismatch disables replay mode.

### 4.5 Theorem 9 (necessity: each rule, removed alone, admits invalid executions) — *proved by construction*
Throughout, $p = \alpha$ (the boundary null) and $\varepsilon = 0.05$. The measured values come from check P5.

| Removed rule | Construction | Analytical consequence | Measured |
|---|---|---|---|
| R3, dedup (CE1) | every result applied twice, so the recorded process is $(E^*)^2$ | crossing $(E^*)^2 \ge 1/\varepsilon$ ⇔ $E^* \ge \varepsilon^{-1/2}$. At $p = \alpha$, $E^*$ is a martingale tending to 0 a.s. Optional stopping at the bounded hitting time gives error $\in [\sqrt\varepsilon/(1+\lambda(1-\alpha)),\ \sqrt\varepsilon] = [0.124, 0.224]$ for λ = 1 | 0.184 |
| R4, fresh retry (CE2) | benign slots crash with $c_0$, violating ones with $c_1 < c_0$; crashed slots re-run with fresh keys | the recorded stream is i.i.d. Bern($p_{\text{eff}}$) with $p_{\text{eff}} = \frac{p(1-c_1)}{p(1-c_1)+(1-p)(1-c_0)} > \alpha$. Any consistent test rejects a.s., so **error → 1** as the cap → ∞ | 0.092 / 0.623 / 0.999 at caps 100 / 1,000 / 4,000 |
| R3, in-order (CE3) | $m$ slots in flight, consumed in arrival order, violations return first | as $m \to \infty$ the processed stream is $S$ ones followed by zeros, with $S \sim \mathrm{Bin}(N,\alpha)$. Crossing ⇔ $S \ge \log(1/a)/\log(1+\lambda(1-\alpha))$, so **error → 1** | 0.030 / 0.219 / 1.000 at $m$ = 1 / 8 / 64 |
| R5 (CE4) | W workers, each spending ε locally | total budget Wε; FWER $= 1-(1-\varepsilon_0)^W \to 1$ | 0.27 (W = 8), 0.72 (W = 32) (Stage 1) |
| R1/A2 (CE5) | 200 candidates scored on a shared fixed key set of 20; the best is "confirmed" on the same keys | maximum selection over N candidates gives **error → 1** as N grows. This also affects the manuscript's Algorithm 1 whenever a shared confirmation seed set feeds back into ranking | 0.699 |
| R2 (CE6) | bet λ = (1/α − η)·Y_{j,i}, i.e. betting with knowledge of the current outcome | factors are $\ge 1$, so wealth never decreases: error → 1 | (trivial) |

### 4.6 Proposition 10 (frontier staleness costs efficiency only) — *proved*
- (a) $\hat b$ is computed by the ledger from CONFIRMED records, so it does not depend on how fast workers learn the frontier.
- (b) If every worker learns each frontier decrease within Δ, and each worker executes at most θ slots per unit time, then the slots spent on candidates with $c_j \ge \hat b$ total at most $K\,W\,\theta\,\Delta$. The reason is that $\hat b$ decreases at most $K$ times, and each decrease wastes at most $\theta\Delta$ per worker.

This is a CALM-style property (Hellerstein & Alvaro, *CACM* 2020): $\hat b$ is a monotone min-register, so dissemination needs no coordination.

### 4.7 Proposition 11 (overshoot and latency trade-off) — *proved*
- With at most $m$ slots of one candidate in flight, at most $m-1$ slots are wasted per confirmation or abandonment.
- The time to confirmation is about $\lceil\tau/m\rceil$ slot durations, plus a head-of-line delay of at most $T_{\text{lease}}$ per gap in the prefix.
- Total waste is at most $J(m-1) + KW\theta\Delta$.

### 4.8 Proposition 12 (parallel time bound) — *proof sketch via Graham list scheduling*
For each realised dependency DAG, with total work $Q_W$ slots, longest dependent chain $D$ (the sequential depth of the adaptive generator), and slot durations at most $T_{\max}$, any greedy scheduler that never idles while a slot is ready satisfies $T_W \le Q_W\bar t/W + D\,T_{\max}$ (Graham, *SIAM J. Appl. Math.* 1969, doi:10.1137/0117039). Here $Q_W \le Q_1 + J(m-1) + KW\theta\Delta$.

Why only a sketch: the DAG itself depends on the schedule, because the search is adaptive. The bound holds per realisation, not as an expectation over schedules. Slots of the same candidate are *not* sequentially dependent for execution; only commit is ordered. So the critical path comes from generator adaptivity, not from confirmation.

### 4.9 Proposition 13 (bit-reproducibility in epoch mode) — *proof sketch*
**Epoch mode.** At each barrier, the scheduler is a deterministic function of the ledger state and the run key. The epoch's slot set has a fixed size $E$, independent of $W$. Results commit at the barrier in canonical $(j,k)$ order. Replay mode is on, and crashed slots are re-leased with the same key until they succeed.

**Claim.** The full ledger, and therefore $(\hat b, j^*, \bar\eta)$, is identical for every $W$ and every crash pattern that eventually lets each slot succeed.

**Argument.** Induction over epochs. Each epoch's inputs are fixed by the previous state, and each slot outcome is a deterministic function of $(\delta, u)$. $W$ changes only wall-clock time. The price is idle time at barriers, about $\mathbb{E}[\max \text{ of } E/W \text{ durations}] - \bar t$ per worker per epoch.

### 4.10 Liveness — *proof sketch*
Liveness holds if the ledger is available, messages are eventually delivered, and each slot is leased finitely often. Each LEASED slot reaches a terminal state within $T_{\text{lease}}$ in async mode, or after finitely many replays in replay mode. So commit pointers advance and the run ends by budget, by $\hat b = 1$, or by the certify-stop rule (§6.1).

---

## 5. Optimisation objective and loss

By Theorems 1 and 8, every scheduling policy $\pi$ that respects R1–R6 is valid. The design problem is therefore an **unconstrained** efficiency problem:

$$\min_\pi\ \mathbb{E}_\pi[\,T_W\,] \quad\text{or}\quad \min_\pi\ \mathbb{E}_\pi[\,Q\,] \qquad \text{until } \hat b \le k^*_\Delta \ \text{or budget},$$

with $k^*_\Delta = \min\{k : \pi_k(\Delta) > 0\}$.

**Evaluation losses** (Stage 4):
- margin regret at budget $q$: $r(q) = \mathbb{E}[\min(\hat b(q), K+1)] - k^*_\Delta$;
- certificate looseness $\bar\eta_k - \mu_k$, which is computable on synthetic instances;
- waste fraction: slots on PRUNED or overshoot work, divided by $Q$;
- coordination overhead: ledger time divided by oracle time.

**Probabilistic uncertainty model** used in simulation (hierarchical):

> family $f$ → scenario $e$ → level $k$ → candidate $\delta \sim D_{e,k}$ with $p(\delta) \sim F_{e,k}$ → slot outcome $\sim \mathrm{Bern}(p)$ → crash $\sim$ Bern($c_0$ or $c_1$, by outcome) → latency $T \mid Y$, which is outcome-dependent and heavy-tailed (lognormal) → optional drift $p_t$.

---

## 6. Algorithms

### 6.1 Algorithm 1: LEXIS-Core (single process; reference `fresco/lexis.py`)
```
Input : reservoirs/generator G_1..G_K, alpha, eps, eps', cap m, weights w, audit share rho,
        audit repeats r, budget Q, bet strategy f
Output: b_hat (or CENSORED), witness, certificates eta_1..eta_K, ledger
 1  b_hat <- inf; j <- 0; spent <- 0
 2  while slots_used < Q and exists k < b_hat:
 3      k <- sample from {k < b_hat} with prob proportional to w_k
 4      if U(0,1) < rho:                                      # audit draw (non-adaptive)
 5          delta ~ D_k; z <- OR_{i=1..r} Y(delta, fresh key)  (crash => z = 1)
 6          N_k += 1; S_k += z; update CS_k(z); continue
 7      if no active candidate at level k:
 8          j <- j + 1; draw delta_j from G_k; a_j <- eps/(j(j+1))   # registration fixes a_j
 9          start e-process E_j (logE = 0, n = 0, s = 0)
10      y <- Y(delta_j, u_{j,n+1}) (crash => 0); lam <- f(s, n)       # prefix-only bet
11      logE_j += log(1 + lam (y - alpha)); n += 1; s += y
12      if logE_j >= log(1/a_j): CONFIRM(j); b_hat <- min(b_hat, k); prune levels >= b_hat
13      elif n >= m: ABANDON(j)
14  eta_k <- bound(N_k, S_k, CS_k; eps'/(2K)) / (1 - (1-alpha)^r)   for every k
15  return (b_hat, witness, eta, ledger)
Optional certify-stop: also stop when eta_k <= eta_target for every k < b_hat.
```

### 6.2 Algorithm 2: FRESCO ledger
This is the guarded-command table of §4.2. It is implemented as serialisable transactions, one per transition. ADVANCE runs inside RECORD and EXPIRE, so commit is incremental, and the ledger publishes $\hat b$ changes on an event stream.

### 6.3 Algorithm 3: FRESCO worker
```
loop:
  if no open lease or lease nearly spent: lease <- GRANT(request x)   # escrow block
  view <- latest frontier b_hat (possibly stale; only efficiency is affected)
  action <- SCHEDULE(view, local generator state)                   # Algorithm 4; any policy is valid
  case action of
    AUDIT(k):          delta ~ D_k; lease r audit slots; run; AUDIT(k, z)
    NEW(k):            delta <- G_k.propose(); REGISTER(lease, delta, a)  (a from spending rule)
    CONTINUE(j, b):    for k in next b unleased slot indices of j:
                           (u, tok) <- LEASE(j, k, self)
                           async: y <- execute(delta_j, u) under deadline T_exec
                                  RECORD(j, k, y, tok)               # idempotent; duplicates ignored
  on crash: nothing to clean up (leases expire; lease budget is forfeited or reclaimed by CLOSE)
  on candidate status change (CONFIRMED/PRUNED/ABANDONED): cancel local in-flight work for it
```

### 6.4 Algorithm 4: scheduling index (heuristic; validity unaffected)
For each active level $k < \hat b$:
- the level weight is $w_k$, which is uniform by default (minimax, Proposition 6);
- with probability ρ, take an audit draw;
- otherwise, among ACTIVE candidates at the level, choose by *progress* $\log E_j / \log(1/a_j)$ with a UCB-style bonus. Open a NEW candidate when the active pool is below $P$, or when every candidate's upper confidence bound on $p$ is below $\alpha+\Delta$ (futility);
- set the in-flight width per candidate to $m_j = \min(m_{\max}, \lceil \text{remaining expected slots}\rceil)$, which trades latency against waste (Proposition 11).

Every heuristic choice here is safe by Theorem 1. Stage 4 ablates them.

---

## 7. Cost analysis

**Notation.** $Q$ = slots (oracle calls); $J$ = registrations; $K$ = levels; $W$ = workers; $L$ = leases; $m$ = in-flight width per candidate; $\bar t$ = mean slot time; $D$ = generator depth.

| Quantity | Bound | Notes |
|---|---|---|
| Best case, oracle calls | $\lceil \log(1/a_1) / \log(1+\lambda_{\max}(1-\alpha)) \rceil$ | 4 slots for α = 0.2 with the plug-in bet, all successes, $a_1 = \varepsilon/2$ |
| Average case (non-adaptive reservoir) | Proposition 5: $O\big(K(\log\frac1\varepsilon + \log J)/(\pi_k\,\mathrm{KL}(\alpha+\Delta\|\alpha))\big)$ | matches the per-candidate lower bound $\Omega(\log(1/a)/\mathrm{KL})$ up to the $K/\pi_k$ search factor (Proposition 6 shows the $K$ is inherent for fixed weights) |
| Worst case | $Q_{\max}$ (censored) | inherent: no finite search proves $R > b$; the budget buys certificates $\bar\eta_k \approx \ln(2K/\varepsilon')/N_k$ |
| Space | ledger $O(J + Q + K)$ rows; worker $O(\text{active candidates} + m)$ | ~100 B per slot row, so 4×10⁷ slots ≈ 4 GB; traces go to content-addressed object storage |
| Messages | $\le 4Q/B + 2Q + 2J + 2L + KW$ | lease batch $B$; results 1 message + 1 ack per slot; frontier fan-out $KW$ (or $O(KW\log W)$ by gossip) |
| Synchronisation | none on the execution path; commit-order wait $\le T_{\text{lease}}$ per gap; epoch mode adds barrier idle time | ledger writes are off the oracle's critical path |
| Parallel time | $T_W \le Q_W\bar t/W + D\,T_{\max}$, with $Q_W \le Q_1 + J(m-1) + KW\theta\Delta$ | near-linear speed-up while $Q_W\bar t/W \gg DT_{\max}$ |
| Coordinator load | ≈ $W/\bar t$ writes/s | **For LLM agents** ($\bar t$ ≈ 5–60 s): W = 32 gives < 10 writes/s, negligible. **For fast synthetic oracles** (μs) the ledger is the bottleneck, so batching is required. The distributed design is justified by correctness and wall-clock time, not by ledger throughput |

**Main trade-offs.**
- Lower ε: cost grows additively in $\log(1/\varepsilon)$.
- α closer to the true $p$: cost grows as $1/\mathrm{KL}$. This is the dominant factor.
- Larger cap $m$: fewer misses, more waste on null candidates.
- Larger audit share ρ: tighter $\bar\eta$ but slower discovery.
- Larger in-flight width: lower latency, up to $m-1$ wasted slots per stop.
- Epoch mode: determinism in exchange for barrier idle time.

---

## 8. Counterexamples and failure conditions of the algorithm itself

1. **Barren cheap levels.** If $\pi_1 = \dots = \pi_{k-1} = 0$, a $(k-1)/K$ share of work is spent forever on empty levels. This is the price in Proposition 6. Mitigation: a certify-stop rule that retires a level once $\bar\eta_k \le \eta_{\text{target}}$. That is a policy decision, not a proof that the level is empty.
2. **Violations that cause crashes are unconfirmable.** If violating trajectories time out with probability $c_1$, the recorded success rate is $p(1-c_1)$. Once $p(1-c_1) \le \alpha$, FRESCO *never* confirms, and $\hat b$ is inflated. The result is conservative but uninformative. Stage 4 must measure $c_1$ and $c_0$ in real harnesses. Replay mode with longer deadlines removes the problem when seeded execution is available.
3. **Hidden state across slots** (violates A1). Example: on the memory surface, a success writes poisoned memory that persists into the next slot. The outcomes then form a Markov chain with $\Pr(Y_{k+1}=1 \mid Y_k=1) > p$. Successes cluster, and the e-process can cross under a stationary mean $\le \alpha$. Fix: a per-slot snapshot reset, as the manuscript requires, plus a runs test on committed streams as a diagnostic.
4. **Oracle false positives** (violates A5). With rate ω ≥ α, a perfectly safe agent is "confirmed" vulnerable. FRESCO certifies $p_{\text{obs}}$, not $p$. The manuscript's independent oracle audit is a prerequisite, not an option.
5. **Seed leakage** (violates A2). If executors log keys that the generator can read, CE5 applies. Fix: the generator runs without access to executor logs, and keys are revealed per lease.
6. **Too many registrations.** Spending $a_j \propto 1/j^2$ means a generator that registers $10^5$ variants faces thresholds of about $\log(1/\varepsilon) + 23$ nats. Fix: scouting-weighted promotion (§3.2), which keeps $J$ small.
7. **Byzantine executors** that fabricate outcomes are not covered. R6 verifies the *computation* but not the *outcomes*. If third-party compute is used, executor attestation or the trace-hash replay audit of §4.4 is needed.
8. **Adaptive generators break Proposition 5's i.i.d. premise.** The efficiency bound covers non-adaptive reservoirs only. Adaptive attackers may do better or worse; that is measured, not proved.

---

## 9. Proof-status table and hypotheses for Stage 4

| ID | Statement | Status |
|---|---|---|
| Thm 1 | LEXIS validity, schedule-oblivious | **Proved** |
| Prop 2, 3 | Anytime certificates (zero-failure exact; betting CS without grid union) | **Proved** |
| Prop 4 | Confirmation time $\Theta(\log(1/a)/\mathrm{KL})$ | **Proved** (upper bound); lower bound via a cited lemma |
| Prop 5 | Expected work per findable level | **Proved** for non-adaptive reservoirs |
| Prop 6 | Uniform weights minimax among fixed weights | **Proved** |
| Cor 7 | Aggregate curve is conservative, uniformly in b | **Proved** |
| Thm 8 | FRESCO validity under asynchrony and faults | **Proved** (reduction) |
| Thm 9 | Necessity of R1–R5 (and R2) | **Proved** by construction (CE1–CE6) |
| Prop 10, 11 | Staleness and overshoot waste bounds | **Proved** |
| Prop 12 | Parallel time bound | **Proof sketch** |
| Prop 13 | Bit-reproducibility in epoch mode | **Proof sketch** |
| Liveness | — | **Proof sketch** |
| Conj A | Some adaptive level schedule beats the factor K on structured (monotone-in-cost) instances | **Conjecture** |
| H-valid | Real agent harnesses show $c_0 \neq c_1$ and non-trivial duplicate or retry rates, so the defaults inflate false confirmations at realistic scale | **Empirical hypothesis** |
| H-coop | At equal total ε, FRESCO (frontier, global scouting-weighted promotion, load balancing) needs fewer oracle calls than W independent ε/W runs to reach $k^*_\Delta$ | **Empirical hypothesis** (Stage 1's B5 restated; may be false) |
| H-speed | Near-linear wall-clock speed-up for W ≤ 32 on LLM-scale slot times, with overhead < 5% | **Empirical hypothesis** |
| H-vs-Alg1 | LEXIS reaches the same $\hat b$ as manuscript Algorithm 1 with fewer oracle calls, at a guaranteed rather than unspecified error level | **Empirical hypothesis** |

## 10. Numerical check summary (`python3 -I sims/stage2_checks.py`, seed 20261018, ~1.5 min)
All proven-bound checks pass, and every counterexample shows the predicted inflation. The full output is in `sims/stage2_checks.out.txt`. These checks confirm agreement between the proofs and an independent implementation on synthetic oracles. They say nothing yet about real agents.

## 11. Inputs to Stage 3
Stage 3 must build the following:
- the ledger schema realising §4.1–4.2 (unique $(j,k)$ keys, token fencing, serialisable transitions);
- a lease service with incarnation binding;
- an event stream for $\hat b$;
- executor sandboxes with per-slot snapshots and deadlines;
- replay-mode detection;
- the offline-escrow reconciliation path;
- a deterministic discrete-event simulator that injects the faults behind CE1–CE5, so Theorem 8 can be tested end-to-end and not only on the statistical core.

## References added in Stage 2 (verified 2026-10-18)
- Kaufmann, Cappé, Garivier. On the complexity of best-arm identification in multi-armed bandit models. *JMLR* 17, 2016. https://jmlr.org/papers/v17/kaufman16a.html
- Genovese, Roeder, Wasserman. False discovery control with p-value weighting. *Biometrika* 93(3), 2006. doi:10.1093/biomet/93.3.509
- Graham. Bounds on multiprocessing timing anomalies. *SIAM J. Appl. Math.* 17(2), 1969. doi:10.1137/0117039
- Brent. The parallel evaluation of general arithmetic expressions. *JACM* 21(2), 1974. doi:10.1145/321812.321815

Stage 1 references are reused: Ville and test supermartingales via Ramdas et al. 2023; Howard et al. 2021; Waudby-Smith & Ramdas; Wald 1945; Hellerstein & Alvaro 2020; O'Neil 1986; Gray & Cheriton 1989.
