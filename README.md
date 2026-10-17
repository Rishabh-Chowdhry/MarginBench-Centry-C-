# MARGIN-Bench → FRESCO research workspace

Staged research programme that develops the MARGIN-Bench manuscript (counterfactual
safety margins for multi-turn / multi-agent LLM systems) into an algorithmic and
distributed-systems contribution.

| Stage | Content | Status |
|---|---|---|
| 1 | Novelty investigation, three candidate directions, selection | [`docs/stage1_novelty_and_directions.md`](docs/stage1_novelty_and_directions.md) |
| 2 | Mathematical framework and algorithm (LEXIS core, FRESCO protocol) | [`docs/stage2_framework_and_algorithm.md`](docs/stage2_framework_and_algorithm.md) |
| 3 | Distributed architecture, protocol, implementation plan | not started |
| 4 | Simulator, experiment scripts, benchmark design, validation | not started |
| 5 | Manuscript (only after evidence exists) | not started |

Code:

- `fresco/` — executable specification of the LEXIS statistical core (betting
  e-process, error-budget ledger, anytime certificates, single-process LEXIS).
- `tests/` — unit tests: `python3 -m pytest -q tests` (needs numpy, pytest).
- `sims/stage1_counterexamples.py`, `sims/stage2_checks.py` — synthetic Monte Carlo
  checks (Bernoulli oracles, no LLM) of the Stage 1 counterexamples and the Stage 2
  propositions. Outputs are committed next to each script (`*.out.txt`).

```
python3 -I sims/stage1_counterexamples.py
python3 -I sims/stage2_checks.py            # ~1.5 min
```

No result in this repository is an empirical finding about real agents.
