#!/usr/bin/env python3
"""
tune.py — sweep a strategy parameter over ALL historical games and report the
most ROBUST value (good across many games, not just peak P&L). Feeds the
review→approve loop and the auto_house model. Does NOT change anything — it just
reports; you apply approved values to strategy_params.json by hand (version bump).

    python3 tune.py conviction edge 0.04 0.06 0.08 0.10 0.12
    python3 tune.py model_revert enter_edge 0.10 0.15 0.20 0.25
    python3 tune.py late_fav price_max 0.85 0.90 0.95
"""
import sys

import backtest
import strategies as strat


def sweep(key, param, values, dataset=None):
    dataset = dataset or backtest.load_all()
    rows = []
    for v in values:
        agg = backtest.run_suite(lambda k: strat.make(k, overrides={param: v}),
                                 [key], dataset)
        a = agg[key]
        wl = a["wins"] + a["losses"]
        rows.append({"value": v,
                     "per_game": a["pnl"] / a["games"] if a["games"] else 0,
                     "win": a["wins"] / wl if wl else 0,
                     "prof": a["profitable_games"], "games": a["games"],
                     "worst": a["worst"], "trades": a["trades"]})
    return rows


def main():
    if len(sys.argv) < 4:
        print("usage: python3 tune.py <strategy> <param> <v1> <v2> ...")
        print("e.g.   python3 tune.py conviction edge 0.04 0.06 0.08 0.10")
        sys.exit(1)
    key, param = sys.argv[1], sys.argv[2]
    vals = [float(x) for x in sys.argv[3:]]
    if key not in strat.REGISTRY:
        print(f"unknown strategy '{key}'. known: {list(strat.REGISTRY)}"); sys.exit(1)
    print(f"Sweeping {key}.{param} over {vals} (net of fees+slippage)…\n")
    rows = sweep(key, param, vals)
    print(f"{param:>9}{'$/game':>9}{'win%':>7}{'prof':>9}{'worst':>9}{'trades':>8}")
    for r in rows:
        print(f"{r['value']:>9}{r['per_game']:>+9.2f}{r['win']*100:>6.0f}%"
              f"{r['prof']:>6}/{r['games']:<2}{r['worst']:>+9.2f}{r['trades']:>8}")
    best = max(rows, key=lambda r: r["per_game"])
    robust = max(rows, key=lambda r: r["per_game"] - abs(r["worst"]) * 0.1)
    cur = strat.load_params().get(key, {}).get(param, "?")
    print(f"\ncurrent: {param}={cur}")
    print(f"best $/game:        {param}={best['value']} ({best['per_game']:+.2f}/game)")
    print(f"most robust (worst-case aware): {param}={robust['value']} ({robust['per_game']:+.2f}/game)")
    print("→ propose in INSIGHTS, get approval, then edit strategy_params.json + bump version.")


if __name__ == "__main__":
    main()
