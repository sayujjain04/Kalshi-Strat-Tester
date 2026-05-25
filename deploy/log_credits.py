#!/usr/bin/env python3
"""Parse `claude -p --output-format json` result from stdin and append the run's
API cost/usage to data/research/credits.jsonl. Defensive: unknown schema → cost 0."""
import datetime, json, os, sys

month = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
model = sys.argv[2] if len(sys.argv) > 2 else "?"
raw = sys.stdin.read().strip()

cost = intok = outtok = turns = 0
try:
    obj = json.loads(raw)
    if isinstance(obj, list):                 # stream-json → take last object
        obj = obj[-1]
    cost = obj.get("total_cost_usd") or obj.get("cost_usd") or 0
    u = obj.get("usage") or {}
    intok = u.get("input_tokens", 0) or 0
    outtok = u.get("output_tokens", 0) or 0
    turns = obj.get("num_turns", 0) or 0
except Exception:
    pass

rec = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
       "month": month, "model": model, "cost_usd": round(float(cost or 0), 4),
       "input_tokens": intok, "output_tokens": outtok, "num_turns": turns}
os.makedirs("data/research", exist_ok=True)
with open("data/research/credits.jsonl", "a") as f:
    f.write(json.dumps(rec) + "\n")
print("credit log:", rec)
