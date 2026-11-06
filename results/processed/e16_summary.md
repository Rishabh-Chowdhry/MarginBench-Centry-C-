# E16: a weighted graph of LLM judges

Judges: Qwen2.5-7B, SmolLM2-1.7B, DeepSeek-R1-7B, gpt-oss-20b. Episodes judged by every judge: 200 (102 calibration, 98 test). Judges never saw AgentDojo's labels.

## Calibration reliabilities and graph weights

Accuracy on the calibration split (Laplace-smoothed), abstentions in brackets; the edge weight is log(acc/(1-acc)).

| Question | Qwen2.5-7B | SmolLM2-1.7B | DeepSeek-R1-7B | gpt-oss-20b |
|---|---|---|---|---|
| TOOL | 0.83 (w=+1.56) | 0.49 (w=-0.04) | 0.66 (w=+0.68) | 0.92 (w=+2.48) |
| TOOL_ERROR | 0.97 (w=+3.52) | 0.91 (w=+2.36) | 0.96 (w=+3.22) | 0.98 (w=+3.93) |
| EXPOSED | 0.81 (w=+1.45) | 0.74 (w=+1.05) | 0.79 (w=+1.34) | 0.97 (w=+3.33) |
| TASK_DONE | 0.74 (w=+1.05) | 0.68 (w=+0.77) | 0.66 (w=+0.68) | 0.84 (w=+1.63) |
| HIJACKED | 0.93 (w=+2.60) | 0.93 (w=+2.60) | 0.90 (w=+2.16) | 0.98 (w=+4.04) |

## Held-out test split

Balanced accuracy (mean of sensitivity and specificity) and Cohen's kappa against the truth.

| Question (test n, positives) | Qwen2.5-7B | SmolLM2-1.7B | DeepSeek-R1-7B | gpt-oss-20b | best | majority | weighted | bayes | ds-em |
|---|---|---|---|---|---|---|---|---|---|
| TOOL (98, 46) | 0.80 / 0.60 | 0.43 / -0.13 | 0.71 / 0.41 | 0.93 / 0.86 | 0.93 / 0.86 | 0.83 / 0.66 | 0.93 / 0.86 | 0.91 / 0.82 | 0.86 / 0.70 |
| TOOL_ERROR (98, 11) | 0.95 / 0.95 | 0.50 / 0.00 | 0.90 / 0.84 | 1.00 / 1.00 | 1.00 / 1.00 | 0.86 / 0.83 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| EXPOSED (54, 11) | 0.91 / 0.88 | 0.50 / 0.00 | 0.49 / -0.04 | 1.00 / 1.00 | 1.00 / 1.00 | 0.50 / 0.00 | 0.91 / 0.88 | 1.00 / 1.00 | 1.00 / 1.00 |
| TASK_DONE (98, 13) | 0.58 / 0.14 | 0.61 / 0.16 | 0.73 / 0.25 | 0.75 / 0.53 | 0.75 / 0.53 | 0.67 / 0.31 | 0.75 / 0.43 | 0.67 / 0.42 | 0.68 / 0.24 |
| HIJACKED (54, 2) | 0.70 / 0.21 | 0.50 / -0.00 | 0.48 / -0.04 | 0.99 / 0.79 | 0.99 / 0.79 | 0.50 / -0.00 | 0.74 / 0.48 | 0.74 / 0.48 | 0.70 / 0.21 |

Cells: balanced accuracy / kappa. `best` = the judge with the highest calibration accuracy on that question: TOOL: gpt-oss-20b, TOOL_ERROR: gpt-oss-20b, EXPOSED: gpt-oss-20b, TASK_DONE: gpt-oss-20b, HIJACKED: gpt-oss-20b.

## Pooled over all questions (test), 95% bootstrap CIs over episodes

| Method | Accuracy | Balanced accuracy | Kappa |
|---|---|---|---|
| Qwen2.5-7B | 0.873 [0.842, 0.904] | 0.840 [0.792, 0.885] | 0.637 [0.541, 0.716] |
| SmolLM2-1.7B | 0.729 [0.700, 0.756] | 0.651 [0.607, 0.698] | 0.267 [0.184, 0.346] |
| DeepSeek-R1-7B | 0.803 [0.768, 0.838] | 0.796 [0.750, 0.844] | 0.497 [0.412, 0.579] |
| gpt-oss-20b | 0.955 [0.935, 0.974] | 0.945 [0.917, 0.971] | 0.867 [0.807, 0.916] |
| best | 0.955 [0.936, 0.972] | 0.945 [0.916, 0.972] | 0.867 [0.809, 0.921] |
| majority | 0.876 [0.841, 0.909] | 0.810 [0.761, 0.864] | 0.620 [0.526, 0.704] |
| weighted | 0.935 [0.913, 0.957] | 0.924 [0.889, 0.956] | 0.811 [0.748, 0.869] |
| bayes | 0.945 [0.925, 0.965] | 0.916 [0.877, 0.951] | 0.833 [0.767, 0.890] |
| ds-em | 0.883 [0.854, 0.912] | 0.900 [0.869, 0.929] | 0.691 [0.612, 0.759] |

## Paired differences in pooled accuracy (test), 95% bootstrap CIs

- weighted − best: -0.020 [-0.039, -0.003]
- weighted − majority: +0.060 [+0.038, +0.084]
- bayes − best: -0.010 [-0.024, +0.002]
- ds-em − majority: +0.007 [-0.017, +0.033]
- weighted − ds-em: +0.052 [+0.028, +0.077]

## Cost

| Judge | Median seconds per episode (4 CPU cores) | Episodes with no valid answer |
|---|---|---|
| Qwen2.5-7B | 9.6 | 0 |
| SmolLM2-1.7B | 3.4 | 0 |
| DeepSeek-R1-7B | 69.7 | 0 |
| gpt-oss-20b | 23.7 | 0 |
