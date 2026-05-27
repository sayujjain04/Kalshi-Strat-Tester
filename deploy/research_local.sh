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
# Robust pull: no global -X union (union is scoped to append-only jsonl via .gitattributes,
# LAB_REVIEW C4); ALWAYS abort a stuck rebase so we never strand a commit mid-rebase (the
# bug that left ~/kalshi-lab detached + unpushed). Mirrors deploy/git_sync.sh.
git pull --rebase --autostash origin main 2>&1 | tail -2 || { git rebase --abort 2>/dev/null || true; }

# close out any game whose Kalshi market settled but whose capture didn't finalize
# (would otherwise show LIVE forever / keep being re-captured)
python3 deploy/finalize_game.py --all 2>&1 | tail -3 || true

# free local compute (no model spend): corpus refresh + analyze + guarded auto-tune +
# board + report, then snapshot the north-star metric for the trend.
python3 historical.py --leagues KXNBAGAME 2>&1 | tail -2 || true
python3 lab_cycle.py --no-commit 2>&1 | tail -4 || true
python3 metrics.py 2>&1 | tail -1 || true

# Creative iteration(s) via your Max-authed Claude (headless, restricted, paper-only).
# It does as many warranted actions as add value, or none — accountable to the trend.
if command -v claude >/dev/null 2>&1; then
  # Save claude's stdout to a file (don't pipe it straight into log_credits — if claude
  # errors/returns non-JSON, piping loses the output AND log_credits throws a JSONDecodeError
  # with no way to see WHY the iteration did nothing — exactly today's failure). Then parse
  # credits from the file and ALWAYS surface a snippet of what claude actually did/errored.
  claude -p "$(cat deploy/research_prompt.md)" \
    --model "$MODEL" --max-turns 50 --output-format json \
    --allowedTools "Read,Edit,Write,Grep,Glob,WebSearch,WebFetch,Bash(python3:*),Bash(git status:*),Bash(git diff:*),Bash(ls:*)" \
    >/tmp/kalshi_cout 2>/tmp/kalshi_cerr || echo "(claude exited non-zero — see /tmp/kalshi_cerr)"
  python3 deploy/log_credits.py "$(date -u +%Y-%m)" "$MODEL" </tmp/kalshi_cout \
    || echo "(credit-log parse failed — claude output was empty/non-JSON; head below)"
  echo "--- claude stdout (head) ---"; head -c 500 /tmp/kalshi_cout 2>/dev/null
  echo "--- claude stderr (tail) ---"; tail -c 500 /tmp/kalshi_cerr 2>/dev/null
else
  echo "claude CLI not on PATH — skipping creative iteration"
fi

python3 metrics.py 2>&1 | tail -1 || true
# The VM owns board generation (it regenerates docs/ on every push for live freshness).
# Discard any locally-generated docs so this loop never commits HTML that conflicts with it.
git checkout -- docs/ 2>/dev/null || true
git clean -fdq docs/ 2>/dev/null || true
git add -A
git commit -m "research(local): autonomous iteration $(date -u +%FT%TZ)" || echo "nothing to commit"
# Robust sync: abort a stuck rebase rather than stranding the commit; retry once.
git pull --rebase --autostash origin main 2>&1 | tail -1 || { git rebase --abort 2>/dev/null || true; }
if ! git push origin main 2>&1 | tail -1; then
  sleep 5
  git pull --rebase --autostash origin main 2>&1 | tail -1 || { git rebase --abort 2>/dev/null || true; }
  git push origin main 2>&1 | tail -1 || echo "push failed"
fi
echo "=== research(local) done ==="
