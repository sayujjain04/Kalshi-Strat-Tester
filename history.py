#!/usr/bin/env python3
"""
history.py — how each strategy has fared over time (the performance ledger).

    python3 history.py                 # all strategies: live record + latest backtest
    python3 history.py conviction      # one strategy: every game it played

Reads data/results/strategy_history.jsonl (appended after each live game and each
backtest run). "live" rows = real forward-tested games; "backtest" rows = a dated
snapshot of the historical sweep at that params version.
"""
import json, os, sys
from collections import defaultdict

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "data", "results", "strategy_history.jsonl")


def _rows():
    if not os.path.exists(LEDGER):
        return []
    return [json.loads(l) for l in open(LEDGER)]


def overall():
    rows = _rows()
    if not rows:
        print("No history yet. Run a live game (run_paper.py) or `python3 backtest.py`.")
        return
    live = defaultdict(lambda: {"games": 0, "net": 0.0, "w": 0, "l": 0})
    last_bt = {}
    for r in rows:
        if r.get("source") == "live":
            a = live[r["strategy"]]
            a["games"] += 1
            a["net"] += r.get("net_pnl") or 0
            a["w"] += r.get("wins") or 0
            a["l"] += r.get("losses") or 0
        elif r.get("source") == "backtest":
            last_bt[r["strategy"]] = r        # keep the latest backtest snapshot

    print("\n══ LIVE (forward-tested games) ══")
    if live:
        print(f"{'strategy':26}{'games':>6}{'net $':>9}{'$/game':>8}{'W/L':>9}")
        for k, a in sorted(live.items(), key=lambda x: -x[1]["net"]):
            wl = f"{a['w']}/{a['l']}"
            print(f"{k:26}{a['games']:>6}{a['net']:>+9.2f}"
                  f"{a['net']/a['games']:>+8.2f}{wl:>9}")
    else:
        print("  (no live games logged yet)")

    print("\n══ latest BACKTEST snapshot (historical sweep) ══")
    if last_bt:
        print(f"{'strategy':26}{'$/game':>8}{'net $':>10}{'W/L':>9}")
        for k, r in sorted(last_bt.items(), key=lambda x: -(x[1].get('per_game') or 0)):
            wl = f"{r.get('wins',0)}/{r.get('losses',0)}"
            print(f"{k:26}{(r.get('per_game') or 0):>+8.2f}{(r.get('net_pnl') or 0):>+10.2f}{wl:>9}")
    else:
        print("  (no backtest logged yet — run python3 backtest.py)")


def one(strategy):
    rows = [r for r in _rows()
            if strategy.lower() in (r.get("strategy", "") + r.get("key", "")).lower()]
    live = [r for r in rows if r.get("source") == "live"]
    if not live:
        print(f"No live games logged for '{strategy}' yet."); return
    print(f"\n══ {live[0]['strategy']} — game by game ══")
    print(f"{'game':28}{'net $':>9}{'W/L':>9}")
    net = 0.0
    for r in live:
        net += r.get("net_pnl") or 0
        wl = f"{r.get('wins',0)}/{r.get('losses',0)}"
        print(f"{r.get('game_id',''):28}{(r.get('net_pnl') or 0):>+9.2f}{wl:>9}")
    print(f"{'TOTAL':28}{net:>+9.2f}  over {len(live)} games")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        one(sys.argv[1])
    else:
        overall()
