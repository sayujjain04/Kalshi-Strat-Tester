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

# Validate every tracked single-object JSON parses; refuse to push if any is corrupt.
# Defense-in-depth against a bad merge silently propagating (LAB_REVIEW C4). JSONL is
# skipped (readers tolerate a stray bad line; .json files are fatal if malformed).
json_ok() {
  python3 - <<'PY'
import json, subprocess, sys
bad = []
for f in subprocess.check_output(["git", "ls-files", "*.json"]).decode().split():
    try:
        json.load(open(f))
    except Exception as e:
        bad.append((f, str(e)[:80]))
if bad:
    print("CORRUPT JSON, refusing to push:", bad[:5]); sys.exit(1)
PY
}

git add -A
git commit -m "$MSG $(date -u +%FT%TZ)" >/dev/null 2>&1 || { echo "nothing to commit"; exit 0; }
# No global -X union: union is scoped to append-only JSONL via .gitattributes. Rewritten
# single-object files (meta.json / strategy_params.json / docs) now conflict->abort instead
# of being concatenated into invalid JSON.
git pull --rebase --autostash origin main >/dev/null 2>&1 || { git rebase --abort >/dev/null 2>&1 || true; }
if ! json_ok; then echo "post-merge JSON check failed: $MSG"; exit 1; fi
if git push origin main >/dev/null 2>&1; then
  echo "pushed: $MSG"
else
  sleep 5
  git pull --rebase --autostash origin main >/dev/null 2>&1 || { git rebase --abort >/dev/null 2>&1 || true; }
  if ! json_ok; then echo "post-merge JSON check failed (retry): $MSG"; exit 1; fi
  git push origin main >/dev/null 2>&1 && echo "pushed (retry): $MSG" || echo "push failed: $MSG"
fi
