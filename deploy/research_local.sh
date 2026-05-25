#!/usr/bin/env bash
# LOCAL autonomous research iteration — uses your Max-plan `claude` login (NO API key,
# no metered billing; it draws on your Claude subscription quota). Runs on this Mac via
# launchd (deploy/com.kalshi.research.plist) ~daily, or manually:  bash deploy/research_local.sh
#
# Free local compute keeps the corpus + baselines + board fresh; ONE creative Claude
# iteration does the judgment work (paper-only, restricted tools). The always-on VM keeps
# capturing live games independently — if this Mac is asleep, we just skip a day.
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")/.."
MODEL="${RESEARCH_MODEL:-claude-sonnet-4-6}"
mkdir -p data/research

echo "=== research(local) $(date -u +%FT%TZ) ==="
git pull --rebase --autostash -X union origin main 2>&1 | tail -2 || true

# free local compute (no model spend): corpus refresh + analyze + guarded auto-tune +
# board + report, then snapshot the north-star metric for the trend.
python3 historical.py --leagues KXNBAGAME 2>&1 | tail -2 || true
python3 lab_cycle.py --no-commit 2>&1 | tail -4 || true
python3 metrics.py 2>&1 | tail -1 || true

# Creative iteration(s) via your Max-authed Claude (headless, restricted, paper-only).
# It does as many warranted actions as add value, or none — accountable to the trend.
if command -v claude >/dev/null 2>&1; then
  claude -p "$(cat deploy/research_prompt.md)" \
    --model "$MODEL" --max-turns 50 --output-format json \
    --allowedTools "Read,Edit,Write,Grep,Glob,WebSearch,WebFetch,Bash(python3:*),Bash(git add:*),Bash(git commit:*),Bash(git status:*),Bash(ls:*)" \
    2>/tmp/kalshi_cerr | python3 deploy/log_credits.py "$(date -u +%Y-%m)" "$MODEL" || echo "(claude iteration skipped)"
  tail -c 400 /tmp/kalshi_cerr 2>/dev/null || true
else
  echo "claude CLI not on PATH — skipping creative iteration"
fi

python3 metrics.py 2>&1 | tail -1 || true
python3 boards.py 2>&1 | tail -1 || true
git add -A
git commit -m "research(local): autonomous iteration $(date -u +%FT%TZ)" || echo "nothing to commit"
git pull --rebase --autostash -X union origin main 2>&1 | tail -1 || true
git push origin main 2>&1 | tail -1 || echo "push failed"
echo "=== research(local) done ==="
