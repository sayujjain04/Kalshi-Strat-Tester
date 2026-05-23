#!/usr/bin/env python3
"""
run_real.py — run ONE strategy with REAL MONEY on Kalshi.   ⚠️ REAL ORDERS ⚠️
──────────────────────────────────────────────────────────────────────────────
Completely separate from the paper tracker (run_paper.py). Defaults to `conviction`
(the only fee-robust earner) with a hard $25 cap and a kill switch.

    python3 run_real.py                 # conviction, $25 cap, pick a game
    python3 run_real.py --capital 25 --max-loss 10 --strategy conviction

Safety (all enforced in RealBroker):
  • capital     — total budget; per-trade stake = capital × strategy.stake_frac
  • max-loss    — kill switch: halts once realized P&L hits −max-loss
  • max-orders  — kill switch: halts after this many orders
  • one position at a time, one ticker, only manages orders it places.
`conviction` holds winners to settlement (Kalshi settles them automatically at
game end) and bails losers early.
"""
import argparse, sys, threading, time
from datetime import datetime, timezone

from kalshi_client import KalshiClient, PROD
from kalshi_feed import KalshiFeed
from espn_feed import ESPNFeed
from real_broker import RealBroker
import strategies as strat
import engine


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def choose(items, render):
    for i, it in enumerate(items):
        print(f"  [{i+1}] {render(it)}")
    if len(items) == 1:
        print("  (only one) — selected.")
        return items[0]
    try:
        return items[int(input(f"\n  Select [1-{len(items)}]: ")) - 1]
    except (ValueError, IndexError, KeyboardInterrupt):
        sys.exit(0)


def run(strategy_key, capital, max_loss, max_orders, assume_yes):
    client = KalshiClient(PROD)
    if strategy_key not in strat.REGISTRY:
        print(f"Unknown strategy '{strategy_key}'. Known: {list(strat.REGISTRY)}"); return
    stake_frac = strat.REGISTRY[strategy_key].stake_frac

    print("Finding NBA games on Kalshi…")
    games = engine.list_live_games(client)
    if not games:
        print("No NBA game markets open."); return
    g = choose(games, lambda x: f'{x["away"]} @ {x["home"]}  [{x["status"].upper()}]  '
               f'{x["score"]["away"]}-{x["score"]["home"]}  ({x["ticker"]})')
    if not g["espn_id"]:
        print("⚠ No ESPN match — model-based strategies can't run. Aborting."); return
    meta = engine.parse_ticker(g["ticker"])

    # ----- confirmation -----
    per_trade = capital * stake_frac
    print("\n" + "=" * 64)
    print("  ⚠️  REAL MONEY — this will place actual orders on your account")
    print("=" * 64)
    print(f"  Strategy   : {strat.REGISTRY[strategy_key].label} ({strategy_key})")
    print(f"  Market     : {g['away']} @ {g['home']}  ({g['ticker']})")
    print(f"  Capital    : ${capital:.2f}   per-trade ≈ ${per_trade:.2f} ({stake_frac:.0%})")
    print(f"  Kill switch: stop at −${max_loss:.2f} realized, or {max_orders} orders")
    print(f"  Status     : game is {g['status'].upper()} "
          f"({'will sit flat until tip-off' if g['status']=='pre' else 'live'})")
    print("=" * 64)
    if not assume_yes and input("  Type 'yes' to start REAL trading: ").strip().lower() != "yes":
        print("Aborted."); return

    import tradelog
    gdir = tradelog.game_dir(engine.game_id(meta))
    broker = RealBroker(g["ticker"], capital=capital, stake_frac=stake_frac,
                        max_loss=max_loss, max_orders=max_orders, log=log,
                        client=client, game_dir=gdir)
    strategy = strat.REGISTRY[strategy_key]()
    strategy.account = broker

    market_state = KalshiFeed(g["ticker"], PROD, log).start()
    plays_seen = []
    espn = ESPNFeed(g["espn_id"], meta["away"], meta["home"], poll_secs=5, log=log,
                    on_new_plays=lambda gs, new: plays_seen.extend(new))
    game_state = espn.start()
    declog = tradelog.DecisionLogger(gdir, "real")
    log(f"LIVE EXECUTION started — {strategy.label} on {g['ticker']} (Ctrl+C to stop)")

    last_sig = None
    try:
        while True:
            market = market_state.snapshot()
            game = game_state.snapshot()
            sig = (game.get("win_prob_ts"), game["score"]["home"],
                   game["score"]["away"], game.get("clock"))
            game_fresh = sig != last_sig
            last_sig = sig
            ctx = engine.make_context(strategy, market, game, meta, broker,
                                      is_replay=False, game_fresh=game_fresh)
            try:
                strategy.evaluate(ctx)
            except Exception as e:
                log(f"strategy error: {e}")

            signal = {"model_p_yes": ctx.model_p_yes, "implied_p_yes": ctx.implied_p_yes,
                      "aligned_implied": ctx.aligned_implied, "model_age_s": ctx.model_age_s,
                      "edge": (None if ctx.model_p_yes is None or ctx.aligned_implied is None
                               else round(ctx.model_p_yes - ctx.aligned_implied, 4))}
            declog.flush({strategy.label: broker}, game, market, signal)

            if broker.halted:
                log("Halted by kill switch. Stopping.")
                break
            if game.get("status") == "post":
                if not broker.flat:
                    log("Game over — position will settle automatically on Kalshi.")
                log("Game finished. Stopping.")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        log("Stopped by user.")

    # summary
    print("\n" + "=" * 64)
    print(f"  REALIZED P&L: ${broker.realized:+.2f}  |  orders placed: {broker.orders_placed}")
    for t in broker.closed:
        print(f"   {t['side'].upper()} {t['count']:g} entry ${t['entry']:.3f} → "
              f"exit ${t['exit']:.3f}  P&L ${t['pnl']:+.3f} {t['result']}")
    if not broker.flat:
        ot = broker.open_trade
        print(f"   STILL HOLDING {ot['side'].upper()} {ot['count']:g} @ ${ot['entry']:.3f} "
              f"(settles on Kalshi at game end)")
    print("=" * 64)


def main():
    ap = argparse.ArgumentParser(description="Run ONE strategy with REAL money (default conviction)")
    ap.add_argument("--strategy", default="conviction")
    ap.add_argument("--capital", type=float, default=25.0)
    ap.add_argument("--max-loss", type=float, default=10.0)
    ap.add_argument("--max-orders", type=int, default=20)
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = ap.parse_args()
    run(a.strategy, a.capital, a.max_loss, a.max_orders, a.yes)


if __name__ == "__main__":
    main()
