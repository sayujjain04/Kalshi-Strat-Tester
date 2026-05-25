#!/usr/bin/env bash
# Headless autonomous research iteration (runs in GitHub Actions). Budget-guarded so
# it never overspends the founder's API credits. Candles/markets/ESPN are public, so
# the corpus refresh needs no secrets — only the model step uses ANTHROPIC_API_KEY.
set -uo pipefail
cd "$(dirname "$0")/.."
MODEL="${RESEARCH_MODEL:-claude-sonnet-4-6}"
BUDGET="${MONTHLY_BUDGET_USD:-25}"
MONTH=$(date -u +%Y-%m)
mkdir -p data/research
LOG=data/research/credits.jsonl

echo "== keep corpus fresh (incremental, free CI compute) =="
python3 historical.py --leagues KXNBAGAME 2>&1 | tail -3 || true

echo "== re-baseline over the full corpus (free CI compute — keeps the e2-micro lean) =="
python3 analyze.py 2>&1 | tail -3 || true
python3 boards.py 2>&1 | tail -2 || true

echo "== monthly API budget guard =="
SPENT=$(python3 - "$LOG" "$MONTH" <<'PY'
import json, sys
log, m = sys.argv[1], sys.argv[2]; t = 0.0
try:
    for l in open(log):
        r = json.loads(l)
        if r.get("month") == m:
            t += r.get("cost_usd", 0) or 0
except FileNotFoundError:
    pass
print(f"{t:.4f}")
PY
)
echo "research API spend this month: \$$SPENT / \$$BUDGET"
if python3 -c "import sys; sys.exit(0 if float('$SPENT') >= float('$BUDGET') else 1)"; then
    echo "monthly budget reached — skipping the model run."; exit 0
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "no ANTHROPIC_API_KEY set — skipping the model run (see docs/OPEN_QUESTIONS.md)."; exit 0
fi

echo "== one autonomous research iteration ($MODEL) =="
# Restricted tool allowlist (NOT a blanket bypass): the agent can read/edit repo
# files, search the web, and run python3/git — bounded to this paper-only repo on an
# ephemeral CI runner with no Kalshi key present. No real-money path exists here.
RES=$(claude -p "$(cat deploy/research_prompt.md)" \
    --model "$MODEL" --max-turns 40 --output-format json \
    --allowedTools "Read,Edit,Write,Grep,Glob,WebSearch,WebFetch,Bash(python3:*),Bash(git add:*),Bash(git commit:*),Bash(git status:*),Bash(ls:*)" \
    2>/tmp/cerr) || true
printf '%s' "$RES" | python3 deploy/log_credits.py "$MONTH" "$MODEL" || echo "(credit parse skipped)"
tail -c 600 /tmp/cerr 2>/dev/null || true
python3 boards.py 2>&1 | tail -2 || true     # reflect the iteration on the board
echo "== research run done =="
