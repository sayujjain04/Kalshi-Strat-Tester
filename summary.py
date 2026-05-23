#!/usr/bin/env python3
"""
summary.py — net gain/loss per strategy for a game.

    python3 summary.py                      # most recent game
    python3 summary.py 20260522_OKC_SAS     # a specific game folder
    python3 summary.py --list               # list all captured games

Reads data/games/<id>/{meta.json, paper_decisions.jsonl, real_decisions.jsonl}.
Each strategy starts with $100 (paper) or its real capital; net = ending − start.
"""
import json, os, sys, glob
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "games")


def _load(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def _games():
    return sorted([d for d in glob.glob(os.path.join(DATA, "*")) if os.path.isdir(d)],
                  key=os.path.getmtime)


def summarize(gdir):
    name = os.path.basename(gdir)
    meta = {}
    mp = os.path.join(gdir, "meta.json")
    if os.path.exists(mp):
        meta = json.load(open(mp))
    print(f"\n══ {name} ══")
    fs = meta.get("final_score") or {}
    if fs.get("home") is not None:
        print(f"Final: {meta.get('away')} {fs.get('away')} – {fs.get('home')} {meta.get('home')}"
              f"   (YES = {meta.get('yes_team')})")

    for mode in ("paper", "real"):
        closes = [d for d in _load(os.path.join(gdir, f"{mode}_decisions.jsonl"))
                  if d.get("event") == "close"]
        if not closes:
            continue
        agg = defaultdict(lambda: {"n": 0, "w": 0, "l": 0, "pnl": 0.0})
        for d in closes:
            a = agg[d["strategy"]]
            a["n"] += 1
            a["pnl"] += d.get("sim", {}).get("sim_pnl") or 0
            r = d.get("sim", {}).get("result")
            a["w"] += r == "WIN"
            a["l"] += r == "LOSS"
        print(f"\n  {mode.upper()} — net P&L per strategy (started at $100 each):")
        print(f"  {'strategy':26}{'trades':>7}{'W/L':>8}{'net $':>9}")
        for k, a in sorted(agg.items(), key=lambda x: -x[1]["pnl"]):
            wl = f"{a['w']}/{a['l']}"
            print(f"  {k:26}{a['n']:>7}{wl:>8}{a['pnl']:>+9.2f}")
        tot = sum(a["pnl"] for a in agg.values())
        print(f"  {'(combined)':26}{'':>7}{'':>8}{tot:>+9.2f}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--list":
        for d in _games():
            print(os.path.basename(d))
        return
    if args:
        gdir = args[0] if os.path.isdir(args[0]) else os.path.join(DATA, args[0])
    else:
        gs = _games()
        if not gs:
            print("No games captured yet (run run_paper.py or pull from the repo)."); return
        gdir = gs[-1]
    if not os.path.isdir(gdir):
        print(f"No such game: {gdir}"); return
    summarize(gdir)


if __name__ == "__main__":
    main()
