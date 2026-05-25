#!/usr/bin/env bash
# VM daily "brain" run: analyze + guarded auto-tune + rebuild board + persist.
# Git push auth comes from the token baked into the remote URL (see setup.sh),
# so no GITHUB_TOKEN env needed here. Run by lab-cycle.service/.timer.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python3}"

"$PY" lab_cycle.py --no-commit || true     # analyze + tune + build docs/ (board+detail+shards)

bash "$(dirname "$0")/git_sync.sh" "vm lab-cycle"   # concurrency-safe commit+push
echo "lab-cycle done"
