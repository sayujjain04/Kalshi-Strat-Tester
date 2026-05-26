#!/usr/bin/env python3
"""
finalize_game.py — close out a stuck/abandoned game so its shard shows FINAL and the
daemon won't re-capture it. A game can be left "live" if its capture thread was killed
(e.g. daemon restart) after the Kalshi market settled but before _save_meta ran, and
it's no longer in today's discovery to self-heal. Settles on the official Kalshi result.

    python3 deploy/finalize_game.py <game_id> [yes|no]   # one game (result auto-fetched)
    python3 deploy/finalize_game.py --all                # every game whose market settled
"""
import glob, json, os, sys

import engine
from kalshi_client import KalshiClient, PROD

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_client = None


def _kc():
    global _client
    if _client is None:
        _client = KalshiClient(PROD)
    return _client


def finalize(gid, result=None, force=False):
    gdir = os.path.join(ROOT, "data", "games", gid)
    mp = os.path.join(gdir, "meta.json")
    if not os.path.exists(mp):
        print(f"{gid}: no meta — skip"); return
    meta = json.load(open(mp))
    if meta.get("final_status"):
        return                                  # already finalized
    if result is None:
        result = engine.kalshi_result(_kc(), meta.get("ticker", ""))
    if result not in ("yes", "no") and not force:
        return                                  # market not settled yet — leave it live
    ticks = []
    for l in open(os.path.join(gdir, "ticks.jsonl")):
        l = l.strip()
        if not l:
            continue
        try:
            ticks.append(json.loads(l))
        except Exception:
            pass
    ticks.sort(key=lambda t: t.get("ts") or "")
    score = (ticks[-1].get("game") or {}).get("score") if ticks else None
    meta["final_status"] = "post"
    meta["kalshi_result"] = result if result in ("yes", "no") else None
    meta["final_score"] = meta.get("final_score") or score
    json.dump(meta, open(mp, "w"))
    print(f"finalized {gid}: result={meta['kalshi_result']} score={meta['final_score']}")


if __name__ == "__main__":
    if "--all" in sys.argv:
        for d in sorted(glob.glob(os.path.join(ROOT, "data", "games", "*"))):
            if os.path.isdir(d) and os.path.exists(os.path.join(d, "meta.json")):
                finalize(os.path.basename(d))
    else:
        finalize(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
