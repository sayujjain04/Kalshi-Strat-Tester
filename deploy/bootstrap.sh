#!/usr/bin/env bash
# Baked into the image. Stable + tiny: clone the repo fresh, then hand off to the
# repo's deploy/run_job.sh so ALL job logic is editable via `git push` (no rebuild).
set -uo pipefail
MODE="${1:-capture}"
REPO="${REPO_SLUG:-sayujjain04/Kalshi-Strat-Tester}"

git config --global user.email "lab-job@users.noreply.github.com"
git config --global user.name "kalshi-lab-job"
if [ -n "${GITHUB_TOKEN:-}" ]; then
  URL="https://${GITHUB_TOKEN}@github.com/${REPO}.git"
else
  URL="https://github.com/${REPO}.git"        # public read-only clone, no push
fi
git clone --depth 80 "$URL" /work
cd /work
exec bash deploy/run_job.sh "$MODE"
