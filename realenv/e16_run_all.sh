#!/bin/sh
# E16 driver: run every judge over the fixed sample, in resumable chunks of at most $1 minutes in total
# (default 100). Rerun until each votes file has as many lines as the sample.
cd "$(dirname "$0")/.." || exit 1
BUDGET=${1:-100}
END=$(( $(date +%s) + 60 * BUDGET ))
for m in smollm2:1.7b qwen2.5:7b gpt-oss:20b deepseek-r1:7b; do
  LEFT=$(( (END - $(date +%s)) / 60 ))
  [ "$LEFT" -le 1 ] && break
  for o in smollm2:1.7b qwen2.5:7b gpt-oss:20b deepseek-r1:7b; do    # one model in memory at a time
    [ "$o" = "$m" ] || curl -s localhost:11434/api/generate -d "{\"model\":\"$o\",\"keep_alive\":0}" >/dev/null
  done
  python3 -I realenv/e16_weighted_judges.py judge "$m" "$LEFT"
done
wc -l results/raw/e16_sample.jsonl results/raw/e16_votes_*.jsonl
