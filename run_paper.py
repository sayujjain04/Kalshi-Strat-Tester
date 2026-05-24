#!/usr/bin/env python3
"""
run_paper.py — NBA live paper-trading tracker
═════════════════════════════════════════════
Runs your strategies against a real Kalshi NBA game on $100 of paper money each,
and surfaces everything on one auto-refreshing dashboard: price candles, the
order flow, ESPN play-by-play, ESPN's live win probability vs. the market's
implied probability, and a journal explaining every trade the strategies make.

Usage
─────
  python3 run_paper.py                       # LIVE: pick from current games, run all strategies
  python3 run_paper.py --replay              # REPLAY a finished game (works any time)
  python3 run_paper.py --strategies model_revert,conviction
  python3 run_paper.py --replay --speed 0.02 # faster replay

Strategies: edge (model-vs-market), runfade (fade scoring runs),
            orderflow (book/tape momentum — live only).
"""
import argparse, os, sys, webbrowser

from kalshi_client import KalshiClient, PROD
import strategies as strat
import engine

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")


def choose(prompt, items, render):
    if not items:
        return None
    print()
    for i, it in enumerate(items):
        print(f"  [{i+1}] {render(it)}")
    if len(items) == 1:
        print(f"\n  Auto-selecting the only option.")
        return items[0]
    try:
        n = int(input(f"\n  {prompt} [1-{len(items)}]: ")) - 1
        return items[n]
    except (ValueError, IndexError, KeyboardInterrupt):
        sys.exit(0)


def run_live(strategy_keys, auto=False, match=None):
    client = KalshiClient(PROD)
    print("Finding NBA games on Kalshi…")
    games = engine.list_live_games(client)
    if not games:
        print("No NBA game markets open right now. Try --replay to test on a finished game.")
        return
    if match:                       # pin a specific game by team (e.g. "OKC")
        ml = match.lower()
        games = [x for x in games if ml in x["away"].lower() or ml in x["home"].lower()]
        if not games:
            print(f"No game matching '{match}' found right now."); return
        print(f"Filtered to games matching '{match}'.")
    if auto:
        # headless (cloud): pick a live game, else the soonest upcoming one
        g = next((x for x in games if x["status"] in ("in", "pre")), None)
        if not g:
            print("No live or upcoming game right now — exiting."); return
        print(f"Auto-selected: {g['away']} @ {g['home']} [{g['status'].upper()}] ({g['ticker']})")
    else:
        g = choose("Select game", games, lambda x:
                   f'{x["away"]} @ {x["home"]}  [{x["status"].upper()}]  '
                   f'{x["score"]["away"]}-{x["score"]["home"]}  ({x["ticker"]})')
        if not g:
            return
    if not g["espn_id"]:
        print("⚠ Couldn't match this game on ESPN — play-by-play/win-prob will be off, "
              "price + order-flow strategies still run.")
    eng = engine.LiveEngine(g["ticker"], g["espn_id"], strat.build(strategy_keys),
                            OUT, refresh=5)
    import dashboard
    dashboard.write(OUT, {"mode": "LIVE", "refresh": 5, "yes_team": g["yes_team"],
                          "game": {"away": g["away"], "home": g["home"],
                                   "score": g["score"], "status": g["status"],
                                   "connected": False},
                          "market": {"connected": False}, "implied_p_yes": None,
                          "model_p_yes": None, "candles": [], "model_series": [],
                          "plays": [], "leaderboard": [], "journal": [], "generated": ""})
    print(f"\nDashboard → {OUT}")
    if not auto:
        print("Opening browser… (Ctrl+C to stop)\n")
        webbrowser.open(f"file://{OUT}")
    eng.run(stop_on_post=auto)        # headless runs exit when the game ends


def _push_data(label):
    import subprocess
    for cmd in (["git", "add", "data/"],
                ["git", "commit", "-m", f"data: {label}"],
                ["git", "push"]):
        subprocess.run(cmd, check=False)
    print("pushed data/ to repo")


def run_daemon(strategy_keys, push_every_s=1800, scan_every_s=120):
    """Always-on VM mode: capture EVERY basketball game (all leagues) CONCURRENTLY.
    Spawns a capture thread per game (each → its own data/games/<id>/ + dashboard),
    reaps them at game end, and periodically pushes data to the repo. Ctrl+C stops."""
    import os, threading, time
    client = KalshiClient(PROD)
    dash_dir = os.path.join(os.path.dirname(OUT), "dashboards")
    os.makedirs(dash_dir, exist_ok=True)
    active = {}                       # game_id -> capture thread
    print("DAEMON: capturing ALL basketball games concurrently (all leagues). Ctrl+C to stop.")

    def capture(g):
        try:
            meta = engine.parse_ticker(g["ticker"])
            out = os.path.join(dash_dir, f"{engine.game_id(meta)}.html")
            engine.LiveEngine(g["ticker"], g["espn_id"], strat.build(strategy_keys),
                              out, refresh=5).run(stop_on_post=True)
        except Exception as e:
            print(f"capture error {g.get('ticker')}: {e}")

    def pusher():
        while True:
            time.sleep(push_every_s)
            try:
                _push_data("daemon periodic")
            except Exception as e:
                print(f"push error: {e}")

    threading.Thread(target=pusher, daemon=True).start()
    try:
        while True:
            try:
                games = engine.list_live_games(client)
            except Exception as e:
                print(f"discovery error: {e}"); time.sleep(scan_every_s); continue
            for g in games:
                # ESPN-matched live/upcoming games stop cleanly at game end;
                # unmatched games are skipped for now (no clean stop signal).
                if g["status"] not in ("in", "pre") or not g["espn_id"]:
                    continue
                gid = engine.game_id(engine.parse_ticker(g["ticker"]))
                if gid in active and active[gid].is_alive():
                    continue
                t = threading.Thread(target=capture, args=(g,), daemon=True)
                t.start(); active[gid] = t
                print(f"▶ capturing [{g['league']}] {g['away']}@{g['home']} ({gid})")
            time.sleep(scan_every_s)
    except KeyboardInterrupt:
        print("daemon stopped.")


def run_replay(strategy_keys, speed):
    client = KalshiClient(PROD)
    print("Finding recently finished NBA games…")
    games = engine.list_recent_finished(days=4)
    if not games:
        print("No finished games found in the last few days.")
        return
    g = choose("Select game to replay", games, lambda x: x["label"])
    if not g:
        return
    ticker = engine.kalshi_ticker_for(client, g["date"], g["away"], g["home"])
    if not ticker:
        print(f"⚠ Couldn't find a Kalshi market for {g['label']} — "
              "price chart will be empty, but play-by-play strategies still run.")
        # fabricate a ticker so parse works for team metadata
        print("Skipping (no market).")
        return
    print(f"Replaying {g['label']} on {ticker} …")
    webbrowser.open(f"file://{OUT}")
    engine.run_replay(g["espn_id"], ticker, strat.build(strategy_keys), OUT,
                      step_delay=speed)
    print(f"\nDashboard → {OUT}")


def main():
    ap = argparse.ArgumentParser(description="NBA live paper-trading tracker")
    ap.add_argument("--replay", action="store_true", help="replay a finished game")
    ap.add_argument("--auto", action="store_true",
                    help="headless: auto-pick the live game, no browser, stop at game end (for cloud)")
    ap.add_argument("--match", default=None,
                    help="run a specific game by team, e.g. --match OKC")
    ap.add_argument("--daemon", action="store_true",
                    help="continuous: auto-track every game + push data to repo (for the VM)")
    ap.add_argument("--strategies", default=",".join(strat.REGISTRY),
                    help="comma-separated: " + ",".join(strat.REGISTRY)
                    + f"  (live-only: {','.join(sorted(strat.LIVE_ONLY))})")
    ap.add_argument("--speed", type=float, default=0.04,
                    help="replay seconds per play (lower = faster)")
    args = ap.parse_args()
    keys = [k.strip() for k in args.strategies.split(",") if k.strip()]
    bad = [k for k in keys if k not in strat.REGISTRY]
    if bad:
        print(f"Unknown strategies: {bad}. Known: {list(strat.REGISTRY)}")
        sys.exit(1)
    if args.replay:
        run_replay(keys, args.speed)
    elif args.daemon:
        run_daemon(keys)
    else:
        run_live(keys, auto=args.auto, match=args.match)


if __name__ == "__main__":
    main()
