#!/usr/bin/env bash
# Control runs for the relay-interference study (2026-09-25): the same 320 cases through OpenRouter (Anthropic
# models pinned to the Anthropic provider), the DeepSeek and Qwen official endpoints, and Qwen Cloud's third-party
# hosting of DeepSeek. Runs one vendor at a time (prompt-cache hits need the same prefix in sequence), resumes a
# vendor's existing run directory when there is one (the smoke runs), scores into a separate report directory so
# the public board is not regenerated, and skips claude-opus-4.7 when the OpenRouter balance is below 9 dollars.
#   bash controls/run-controls-v1.sh > controls/run-controls-v1.log 2>&1 &
# Resume after an interruption: run the same command; finished vendors are skipped by run.py's resume.
set -u
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
R="C:/Users/easts/AppData/Local/Temp/claude/C--Users-easts--claude/2636cffd-b870-41e2-a037-da06de2ed4e9/scratchpad/controls-report"
mkdir -p "$R"
K=$(sed -n 's/^OPENROUTER_API_KEY=//p' ~/.ilang-conformance.env | tr -d '\r')
credits() { curl -s --max-time 30 -H "Authorization: Bearer $K" https://openrouter.ai/api/v1/credits | python -c "import json,sys; d=json.load(sys.stdin)['data']; print(round(d['total_credits']-d['total_usage'],2))" 2>/dev/null || echo 0; }
VENDORS="openrouter-anthropic-claude-sonnet-4.6 openrouter-anthropic-claude-haiku-4.5 deepseek-official-deepseek-flash qwen-official-qwen3.8-flash openrouter-deepseek-deepseek-v4.1-flash openrouter-qwen-qwen3.8-flash openrouter-z-ai-glm-5.3-flash qwen-official-deepseek-v4.1-flash openrouter-anthropic-claude-opus-4.7"
for v in $VENDORS; do
  echo "=== $(date -u +%FT%TZ) $v openrouter_balance=$(credits)"
  if [ "$v" = "openrouter-anthropic-claude-opus-4.7" ]; then
    bal=$(credits)
    if python -c "import sys; sys.exit(0 if float('$bal') >= 9 else 1)"; then :; else echo "skip $v: balance $bal below 9"; continue; fi
  fi
  d=$(ls -d runs/$v-2026* 2>/dev/null | tail -1)
  if [ -n "$d" ]; then args="--run-dir $d"; else args=""; fi
  python run.py --vendor "$v" --concurrency 2 $args || echo "RUN FAILED $v"
  d=$(ls -d runs/$v-2026* 2>/dev/null | tail -1)
  [ -n "$d" ] || continue
  python score.py "$d" --vendor "$v" --report "$R" || echo "SCORE FAILED $v"
  python refusal.py "$d" --report "$R" || echo "REFUSAL FAILED $v"
done
python refusal.py --table --report "$R" || true
echo "=== ALL DONE $(date -u +%FT%TZ) openrouter_balance=$(credits)"
