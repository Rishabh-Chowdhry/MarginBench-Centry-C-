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
| 5 | Manuscript + independent peer review | [`paper/fresco_manuscript.tex`](paper/fresco_manuscript.tex) ([PDF](paper/fresco_manuscript.pdf)), [`docs/stage5_peer_review.md`](docs/stage5_peer_review.md) |

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
`tectonic paper/fresco_manuscript.tex`); see the header comment for porting to the
Springer Nature `sn-jnl` template.

No result in this repository is an empirical finding about real agents.
