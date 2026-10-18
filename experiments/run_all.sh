#!/usr/bin/env bash
# Reproduce every Stage-4 result (synthetic). Total about 1.5-2 h on 4 cores.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -I experiments/e2_scaling.py 100
python3 -I experiments/e1_validity.py 400
python3 -I experiments/e4_alg1.py 2000
python3 -I experiments/e5_ablations.py 80
python3 -I experiments/e6_recovery.py 30
python3 -I experiments/e7_certificates.py 200
python3 -I sims/stage3_fault_injection.py 400 > sims/stage3_fault_injection.out.txt
python3 -I experiments/e8_hybrid.py 2000
python3 -I experiments/e9_fixed_n_rules.py > results/processed/e9_fixed_n_rules.txt
python3 -I analysis/make_figures.py
