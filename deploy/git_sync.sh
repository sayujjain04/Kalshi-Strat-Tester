#!/usr/bin/env bash
# Concurrency-safe commit+push. The capture daemon and the lab-cycle both write
# into the same repo, so all git access is serialized with an flock, and
# --autostash absorbs files the daemon writes mid-rebase. Auth comes from the
# token in the remote URL (set by setup.sh). Usage: git_sync.sh "message"
set -uo pipefail
cd "$(dirname "$0")/.."
MSG="${1:-sync}"

exec 9>/tmp/kalshi_git.lock
flock 9                                  # one git operation in this repo at a time

git add -A
git commit -m "$MSG $(date -u +%FT%TZ)" >/dev/null 2>&1 || { echo "nothing to commit"; exit 0; }
git pull --rebase --autostash -X union origin main >/dev/null 2>&1 || { git rebase --abort >/dev/null 2>&1 || true; }
if git push origin main >/dev/null 2>&1; then
  echo "pushed: $MSG"
else
  sleep 5
  git pull --rebase --autostash -X union origin main >/dev/null 2>&1 || true
  git push origin main >/dev/null 2>&1 && echo "pushed (retry): $MSG" || echo "push failed: $MSG"
fi
