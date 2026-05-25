#!/usr/bin/env bash
# The actual Cloud Run Job logic, run from the freshly-cloned repo (/work).
# Editable via `git push` — the image only clones + calls this.
# MODE = capture | lab-cycle. Secrets arrive as env vars (KALSHI_KEY_ID,
# KALSHI_PEM read by kalshi_creds.py; GITHUB_TOKEN to push results).
set -uo pipefail
MODE="${1:-capture}"

echo "== Cloud Run Job: $MODE =="
if [ "$MODE" = "lab-cycle" ]; then
  python3 lab_cycle.py --no-commit || true        # analyze + guarded tune + boards + report
else
  python3 run_paper.py --once --max-hours "${MAX_HOURS:-8}" || true
  python3 boards.py || true                        # refresh the board after capture
fi

# package the board + per-game dashboards for GitHub Pages (served from /docs)
mkdir -p docs/games
[ -f boards.html ] && cp boards.html docs/index.html
if [ -d dashboards ]; then cp dashboards/*.html docs/games/ 2>/dev/null || true; fi

if [ -n "${GITHUB_TOKEN:-}" ]; then
  git add -A                                        # everything the job changed: params, data, docs
  git commit -m "job:$MODE $(date -u +%FT%TZ)" || { echo "nothing to commit"; exit 0; }
  git config pull.rebase true
  git pull --rebase -X union origin main || git rebase --abort || true
  git push origin main || { sleep 5; git pull --rebase -X union origin main; git push origin main; } \
    || echo "push failed"
fi
echo "== job done =="
