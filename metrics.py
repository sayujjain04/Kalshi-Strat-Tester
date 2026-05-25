#!/usr/bin/env python3
"""
metrics.py — append a deterministic lab-health snapshot to data/research/metrics.jsonl
so we can SEE, over time, whether iterations are actually pushing toward higher / more
consistent profit. Free: reads the ledger (run it AFTER lab_cycle has refreshed the
backtest rows). The research loop reads this trend and is accountable to it — if the
north-star stalls or drops, the loop must change course.

North-star = the risk-adjusted backtest score of our best DEPLOYABLE (non-control)
strategy on the full corpus: per_game − 0.5·|worst game| (rewards return, penalizes the
short-vol tail). Tracked alongside forward (live) evidence so we never confuse a
backtest gain with a real, out-of-sample one.

    python3 metrics.py
"""
import datetime, glob, json, os
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(ROOT, "data", "results", "strategy_history.jsonl")
GAMES = os.path.join(ROOT, "data", "games")
CORPUS = os.path.join(ROOT, "data", "backtest")
OUT = os.path.join(ROOT, "data", "research", "metrics.jsonl")
CONTROL = {"edge_naive"}          # baseline-to-beat, not a deployable edge


def _ledger():
    return [json.loads(l) for l in open(LEDGER)] if os.path.exists(LEDGER) else []


def robustness(per_game, worst):
    return round((per_game or 0) - 0.5 * abs(worst or 0), 3)


def snapshot():
    rows = _ledger()
    bt, live = {}, defaultdict(lambda: {"games": 0, "net": 0.0, "w": 0, "l": 0})
    for r in rows:
        k = r.get("key") or r.get("strategy")
        if r.get("source") == "backtest":
            bt[k] = r
        elif r.get("source") == "live":
            a = live[k]
            a["games"] += 1; a["net"] += r.get("net_pnl") or 0
            a["w"] += r.get("wins") or 0; a["l"] += r.get("losses") or 0

    best, best_score = None, None
    for k, r in bt.items():
        if k in CONTROL:
            continue
        sc = robustness(r.get("per_game"), r.get("worst"))
        if best_score is None or sc > best_score:
            best, best_score = k, sc

    fwd_bets = sum(a["w"] + a["l"] for a in live.values())
    bl = live.get(best, {})
    bt_pg = (bt.get(best) or {}).get("per_game")
    fwd_pg = round(bl["net"] / bl["games"], 3) if bl.get("games") else None
    # decay = how much worse forward is than backtest. Large positive = overfit alarm.
    decay = round(bt_pg - fwd_pg, 3) if (bt_pg is not None and fwd_pg is not None) else None
    snap = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "north_star": best_score,                                  # robustness of best deployable (backtest)
        "best_strategy": best,
        "bt_per_game": bt_pg,
        "bt_worst": (bt.get(best) or {}).get("worst"),
        "backtest_games": len(glob.glob(os.path.join(CORPUS, "*.json.gz"))),
        "captured_games": len([d for d in glob.glob(os.path.join(GAMES, "*")) if os.path.isdir(d)]),
        "forward_bets": fwd_bets,                                  # progress toward the ~100-OOS-bet bar
        "fwd_per_game": fwd_pg,
        "decay": decay,                                            # bt − fwd; big + = overfit warning
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(snap) + "\n")
    print("metrics:", snap)
    return snap


if __name__ == "__main__":
    snapshot()
