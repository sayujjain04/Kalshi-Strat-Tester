#!/usr/bin/env python3
"""
backtest.py — multi-game backtester for the REPLAYABLE strategies.
(The live-only strategies — wp_momentum, spread_cap, flow_confirm — need live
order flow and can't be backtested; they're skipped here.)

Pulls every finished NBA game with a resolvable Kalshi market + candles + win
probability, caches the raw game data to disk, and runs strategies across all of
them so parameter choices are made on aggregate results, not one game.

  python3 backtest.py                 # baseline, default params, all games
  (or import and call run_suite(...) for parameter sweeps)
"""
import json, os, pickle
from datetime import datetime, timezone

import requests

from kalshi_client import KalshiClient, PROD
from espn_feed import espn_abbr
import engine
import strategies as strat

CACHE_DIR = "/tmp/bt_cache"
GAMES_JSON = "/tmp/testable_games.json"
ESPN = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba"


# ── game discovery (cached) ───────────────────────────────────────────────────
def discover_games(days=35, refresh=False):
    if os.path.exists(GAMES_JSON) and not refresh:
        return json.load(open(GAMES_JSON))
    s = requests.Session(); s.headers["User-Agent"] = "r/2.0"
    client = KalshiClient(PROD)
    finished = []
    for back in range(days):
        d = datetime.now(timezone.utc)
        d = d.fromordinal(d.toordinal() - back)
        try:
            r = s.get(f"{ESPN}/scoreboard", params={"dates": d.strftime("%Y%m%d")},
                      timeout=12).json()
        except Exception:
            continue
        for ev in r.get("events", []):
            c = ev["competitions"][0]
            if c["status"]["type"]["state"] != "post":
                continue
            cs = {x["homeAway"]: x for x in c["competitors"]}
            finished.append({"espn_id": ev["id"], "date": d.strftime("%Y%m%d"),
                             "away": cs["away"]["team"]["abbreviation"],
                             "home": cs["home"]["team"]["abbreviation"]})
    idx = {}
    for st in ("settled", "finalized"):
        for m in client.markets(series_ticker="KXNBAGAME", status=st, limit=200):
            p = engine.parse_ticker(m["ticker"])
            if p and m["ticker"].endswith(p["away"]):
                idx[(p["date"], frozenset({espn_abbr(p["away"]), espn_abbr(p["home"])}))] = m["ticker"]
    games = [{**g, "ticker": idx[(g["date"], frozenset({g["away"], g["home"]}))]}
             for g in finished
             if (g["date"], frozenset({g["away"], g["home"]})) in idx]
    json.dump(games, open(GAMES_JSON, "w"))
    return games


def game_data(game):
    """fetch_replay_data with on-disk caching."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{game['espn_id']}.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    data = engine.fetch_replay_data(game["espn_id"], game["ticker"])
    pickle.dump(data, open(path, "wb"))
    return data


def load_all(limit=None):
    games = discover_games()
    out = []
    for g in (games[:limit] if limit else games):
        try:
            d = game_data(g)
        except Exception:
            d = None
        if d and d.get("candles") and len(d["candles"]) > 5:
            out.append((g, d))
    return out


# ── running strategies across all games ───────────────────────────────────────
def run_suite(factory, keys, dataset, stake_frac=None, slippage=None):
    """
    factory(key) -> a fresh Strategy instance (with whatever params).
    Returns {key: {games, trades, wins, losses, pnl, profitable_games, worst}}.
    """
    agg = {k: {"games": 0, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
               "profitable_games": 0, "worst": 0.0, "best": 0.0} for k in keys}
    for g, data in dataset:
        meta = engine.parse_ticker(g["ticker"])
        strategies = []
        for k in keys:
            st = factory(k)
            if stake_frac is not None:
                st.stake_frac = stake_frac
            strategies.append(st)
        engine.simulate(meta, data, strategies, slippage=slippage)
        for st in strategies:
            acc = st.account
            a = agg[st.key]
            a["games"] += 1
            a["trades"] += len(acc.closed)
            a["wins"] += sum(1 for t in acc.closed if t.result == "WIN")
            a["losses"] += sum(1 for t in acc.closed if t.result == "LOSS")
            gp = acc.realized
            a["pnl"] += gp
            a["profitable_games"] += 1 if gp > 0 else 0
            a["worst"] = min(a["worst"], gp)
            a["best"] = max(a["best"], gp)
    return agg


def fmt(agg, label="results"):
    print(f"\n=== {label} ===")
    print(f"{'strategy':16}{'games':>6}{'trades':>7}{'W/L':>9}{'win%':>6}"
          f"{'tot P&L':>10}{'$/game':>8}{'prof':>7}{'worst':>8}")
    for k, a in agg.items():
        wl = a["wins"] + a["losses"]
        wr = (a["wins"] / wl * 100) if wl else 0
        per = a["pnl"] / a["games"] if a["games"] else 0
        wlstr = f"{a['wins']}/{a['losses']}"
        profstr = f"{a['profitable_games']}/{a['games']}"
        print(f"{k:16}{a['games']:>6}{a['trades']:>7}{wlstr:>9}{wr:>5.0f}%"
              f"{a['pnl']:>+10.2f}{per:>+8.2f}{profstr:>7}{a['worst']:>+8.2f}")


if __name__ == "__main__":
    REPLAYABLE = ["edge_naive", "model_revert", "run_fade", "late_fav"]
    print("Loading games (cached after first run)…")
    dataset = load_all()
    print(f"{len(dataset)} testable games loaded.")
    agg = run_suite(lambda k: strat.REGISTRY[k](), REPLAYABLE, dataset)
    fmt(agg, "BASELINE (default params, $20/trade)")
