#!/usr/bin/env bash
# Cloud Run Job entrypoint. MODE = capture | lab-cycle (default capture).
# Clones the repo fresh (latest code + data), runs the job, regenerates the
# board, packages it for GitHub Pages (docs/), and commits results back.
# Secrets arrive as env vars: KALSHI_KEY_ID, KALSHI_PEM (read by kalshi_creds.py),
# GITHUB_TOKEN (to clone+push).
set -uo pipefail
MODE="${1:-capture}"
REPO="${REPO_SLUG:-sayujjain04/Kalshi-Strat-Tester}"

git config --global user.email "lab-job@users.noreply.github.com"
git config --global user.name "kalshi-lab-job"

if [ -n "${GITHUB_TOKEN:-}" ]; then
  URL="https://${GITHUB_TOKEN}@github.com/${REPO}.git"
else
  URL="https://github.com/${REPO}.git"        # public clone (read-only, no push)
fi
git clone --depth 80 "$URL" /work
cd /work

echo "== Cloud Run Job: $MODE =="
if [ "$MODE" = "lab-cycle" ]; then
  python3 lab_cycle.py --no-commit || true        # analyze + tune + boards + report
else
  python3 run_paper.py --once --max-hours "${MAX_HOURS:-8}" || true
  python3 boards.py || true                        # refresh the board after capture
fi

# package the board + game shards for GitHub Pages (served from /docs)
mkdir -p docs/games
[ -f boards.html ] && cp boards.html docs/index.html
if [ -d dashboards ]; then cp dashboards/*.html docs/games/ 2>/dev/null || true; fi

if [ -n "${GITHUB_TOKEN:-}" ]; then
  git add data/ docs/ 2>/dev/null || true
  git commit -m "job:$MODE $(date -u +%FT%TZ)" || echo "nothing to commit"
  git push origin main || echo "push failed"
fi
echo "== job done =="
