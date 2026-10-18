# MARGIN-Bench → FRESCO research workspace

Staged research programme that develops the MARGIN-Bench manuscript (counterfactual
safety margins for multi-turn / multi-agent LLM systems) into an algorithmic and
distributed-systems contribution.

| Stage | Content | Status |
|---|---|---|
| 1 | Novelty investigation, three candidate directions, selection | [`docs/stage1_novelty_and_directions.md`](docs/stage1_novelty_and_directions.md) |
| 2 | Mathematical framework and algorithm (LEXIS core, FRESCO protocol) | [`docs/stage2_framework_and_algorithm.md`](docs/stage2_framework_and_algorithm.md) |
| 3 | Distributed architecture, protocol, implementation plan | [`docs/stage3_architecture_and_implementation.md`](docs/stage3_architecture_and_implementation.md) |
| 4 | Simulator, experiment scripts, benchmark design, validation | [`docs/stage4_experiments_and_validation.md`](docs/stage4_experiments_and_validation.md) |
| 5 | Manuscript + independent peer review | v2, reframed around execution rules: [`paper/manuscript.tex`](paper/manuscript.tex) ([PDF](paper/manuscript.pdf)); v1 in `paper/archive/`; review: [`docs/stage5_peer_review.md`](docs/stage5_peer_review.md) |
| 6 | Screening + LEXIS hybrid (preregistered follow-up) | [`docs/stage6_hybrid_screening_lexis.md`](docs/stage6_hybrid_screening_lexis.md) |
| 7 | QUINTET (five coordinators), heterogeneous evidence graph, TWGR repair; proofs, ablations, Docker SQA campaign, real AgentDojo agents | [`docs/stage7_quintet_hkg_twgr.md`](docs/stage7_quintet_hkg_twgr.md), [`realenv/TEST_PLAN.md`](realenv/TEST_PLAN.md), [`realenv/RESULTS.md`](realenv/RESULTS.md) |

Code:

- `fresco/` — executable specification of the LEXIS statistical core (betting
  e-process, error-budget ledger, anytime certificates, single-process LEXIS),
  the FRESCO ledger state machine and protocol messages (`ledger.py`,
  `messages.py`), and a deterministic fault-injection simulator (`fresco/sim/`).
- `deploy/postgres_schema.sql` — production ledger schema (specification; not yet executed).
- `tests/` — unit tests: `python3 -m pytest -q tests` (needs numpy, pytest).
- `sims/stage1_counterexamples.py`, `sims/stage2_checks.py`, `sims/stage3_fault_injection.py`
  — synthetic Monte Carlo checks (no LLM) of the Stage 1 counterexamples, the Stage 2
  propositions, and system-level fault injection through the implemented protocol.
  Outputs are committed next to each script (`*.out.txt`).

```
python3 -I sims/stage1_counterexamples.py
python3 -I sims/stage2_checks.py            # ~1.5 min
python3 -I sims/stage3_fault_injection.py   # ~12 min on 4 cores (400 runs per config)
```

Stage 4 experiments (synthetic): `experiments/run_all.sh` reruns E1-E7 and the Stage 3
fault injection (~1.5-2 h on 4 cores) and regenerates `results/processed/summary.md` and
`figures/` via `analysis/make_figures.py`.

The manuscript (`paper/`) compiles with any LaTeX engine (built here with tectonic:
`tectonic paper/manuscript.tex`); see the header comment for porting to the
Springer Nature `sn-jnl` template.

Stage 7 (corruption tolerance and real environments):

```
python3 -I experiments/e10_corruption.py 40     # TWGR ablations under storage corruption (~1 h, 4 cores)
python3 -I experiments/e11_adversary.py 20      # coordinated adversary controlling k domains
realenv/build_image.sh                          # device image (Docker)
TOXIPROXY_BIN=/path/to/toxiproxy-server python3 -I realenv/sqa_campaign.py /tmp/sqa   # E12, ~30 min
python3 realenv/e13_agentdojo.py qwen2.5:1.5b 120   # E13: AgentDojo + Ollama (OpenAI-compatible API on :11434)
python3 -I analysis/stage7_figures.py           # results/processed/stage7_summary.md, figures/fig1[0-5]_*.png
```

- `fresco/hkg/` — heterogeneous evidence graph (`graph.py`), TWGR repair (`repair.py`), corruption injector (`corrupt.py`).
- `fresco/quintet/` — the five coordinators in process (`cluster.py`) and as networked services plus workers (`service.py`).
- `realenv/` — Docker device image, SQA harness, on-disk corruption, AgentDojo episode runner.

All validity and recovery claims rest on synthetic ground truth. The only real-agent
data are the E13 AgentDojo episodes (descriptive; see `realenv/RESULTS.md`).
