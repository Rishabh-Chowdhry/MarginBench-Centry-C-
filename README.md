# MARGIN-Bench → FRESCO research workspace

Staged research programme that develops the MARGIN-Bench manuscript (counterfactual
safety margins for multi-turn / multi-agent LLM systems) into an algorithmic and
distributed-systems contribution.

| Stage | Content | Status |
|---|---|---|
| 1 | Novelty investigation, three candidate directions, selection | [`docs/stage1_novelty_and_directions.md`](docs/stage1_novelty_and_directions.md) |
| 2 | Mathematical framework and algorithm (LEXIS core, FRESCO protocol) | not started |
| 3 | Distributed architecture, protocol, implementation plan | not started |
| 4 | Simulator, experiment scripts, benchmark design, validation | not started |
| 5 | Manuscript (only after evidence exists) | not started |

`sims/stage1_counterexamples.py` is a synthetic Monte Carlo sanity check (Bernoulli
oracle, no LLM) of the counterexamples argued in Stage 1. Reproduce with:

```
python3 -I sims/stage1_counterexamples.py   # requires numpy; output in sims/stage1_counterexamples.out.txt
```

No result in this repository is an empirical finding about real agents.
