#!/usr/bin/env bash
# VM daily "brain" run: analyze + guarded auto-tune + rebuild board + persist.
# Git push auth comes from the token baked into the remote URL (see setup.sh),
# so no GITHUB_TOKEN env needed here. Run by lab-cycle.service/.timer.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python3}"

"$PY" lab_cycle.py --no-commit || true     # analyze + guarded tune + report (no git here)

# refresh the GitHub Pages board (served from docs/)
mkdir -p docs/games
[ -f boards.html ] && cp boards.html docs/index.html
[ -d dashboards ] && cp dashboards/*.html docs/games/ 2>/dev/null || true

bash "$(dirname "$0")/git_sync.sh" "vm lab-cycle"   # concurrency-safe commit+push
echo "lab-cycle done"
