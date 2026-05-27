#!/usr/bin/env python3
"""
analyze_clv.py — Closing-Line Value (CLV) analysis for Q4 entries.

For each auto_house (or conviction) trade, computes:
    CLV = P_close(+Ns) - entry_price   (YES trades)
        = entry_price - P_close(+Ns)   (NO trades)

where P_close(+Ns) is the Kalshi market close price N seconds after entry.

CLV > 0 means the market moved in our favour after entry — we bought below
the subsequent market consensus. A systematically positive average CLV is the
gold standard for genuine edge (independent of win/loss outcomes which are noisy).

Industry gate: >55% of trades with positive CLV over 200+ observations
              signals genuine edge (see EXP-006).

Usage:
    python3 analyze_clv.py              # auto_house, CLV window = 120s
    python3 analyze_clv.py conviction   # conviction
    python3 analyze_clv.py auto_house 90   # 90-second window
"""
import re, sys, statistics
from collections import defaultdict

import backtest
import strategies as strat
import engine


WINDOW_S_DEFAULT = 120    # seconds after entry to measure closing price


def _iso_to_unix(s):
    from engine import _iso_to_unix as f
    return f(s)


def find_entry_ts(entry_clock, plays):
    """Return Unix timestamp of the play closest to entry_clock string ('Q4 4:51')."""
    m = re.match(r"Q(\d+)\s+(\d+):(\d+)", entry_clock or "")
    if not m:
        return None
    q, mins, secs = int(m.group(1)), int(m.group(2)), int(m.group(3))
    target_s = mins * 60 + secs

    best_ts, best_diff = None, 999999
    for p in plays:
        if p.get("period", {}).get("number") != q:
            continue
        wc = p.get("wallclock")
        if not wc:
            continue
        clk = p.get("clock", {}).get("displayValue", "")
        cm = re.match(r"(\d+):(\d+)", clk)
        if not cm:
            continue
        ps = int(cm.group(1)) * 60 + int(cm.group(2))
        diff = abs(ps - target_s)
        if diff < best_diff:
            best_diff = diff
            best_ts = _iso_to_unix(wc)

    return best_ts if best_diff < 30 else None   # reject if >30s mismatch


def candle_close_at(candles, ts, window_s):
    """Return the candle close price closest to ts + window_s."""
    target = ts + window_s
    best_c, best_diff = None, 999999
    for c in candles:
        if c.get("c") is None:
            continue
        diff = abs(c.get("ts", 0) - target)
        if diff < best_diff:
            best_diff = diff
            best_c = c.get("c")
    return best_c if best_diff < 90 else None   # reject if no candle within 90s


def run(strategy_key="auto_house", window_s=WINDOW_S_DEFAULT):
    print(f"\nLoading corpus ...", flush=True)
    dataset = backtest.load_all()
    print(f"{len(dataset)} games. Strategy: {strategy_key}  CLV window: {window_s}s")

    clv_values = []       # (clv, result, entry_price, entry_clock)
    skipped = 0

    for g, data in dataset:
        plays   = data.get("plays", [])
        candles = data.get("candles", [])
        s = strat.make(strategy_key)
        meta = engine.parse_ticker(g["ticker"])
        engine.simulate(meta, data, [s])

        for t in s.account.closed:
            ts = find_entry_ts(t.entry_clock, plays)
            if ts is None:
                skipped += 1
                continue
            close_p = candle_close_at(candles, ts, window_s)
            if close_p is None:
                skipped += 1
                continue
            clv = (close_p - t.entry_price) if t.side == "yes" else (t.entry_price - close_p)
            clv_values.append((clv, t.result, t.entry_price, t.entry_clock, t.pnl))

    n = len(clv_values)
    if n == 0:
        print("No CLV-able trades found.")
        return

    clvs    = [x[0] for x in clv_values]
    pos_pct = sum(1 for c in clvs if c > 0) / n * 100
    avg_clv = statistics.mean(clvs)
    med_clv = statistics.median(clvs)

    wins_with_pos_clv  = sum(1 for c, r, *_ in clv_values if c > 0 and r == "WIN")
    wins_total         = sum(1 for _, r, *_ in clv_values if r == "WIN")
    losses_pos_clv     = sum(1 for c, r, *_ in clv_values if c > 0 and r == "LOSS")

    print(f"\n{'='*65}")
    print(f"  CLV SUMMARY — {n} trades  ({skipped} skipped, no matching play/candle)")
    print(f"{'='*65}")
    print(f"  Avg CLV         : {avg_clv:+.4f}  ({avg_clv*100:+.2f}¢)")
    print(f"  Median CLV      : {med_clv:+.4f}  ({med_clv*100:+.2f}¢)")
    print(f"  % trades +CLV   : {pos_pct:.1f}%   (gate: >55%)")
    print(f"  Total trades    : {n}  (target: 200+)")
    print()
    print(f"  Outcome breakdown:")
    print(f"    WIN  + pos CLV : {wins_with_pos_clv}/{wins_total} wins had pos CLV "
          f"({wins_with_pos_clv/wins_total*100:.0f}% of wins)")
    print(f"    LOSS + pos CLV : {losses_pos_clv}/{n-wins_total} losses had pos CLV "
          f"(adversely selected?)")
    print()

    # ── by CLV bucket ──
    buckets = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    for clv, result, ep, clk, pnl in clv_values:
        if clv < -0.10:  k = "< -10¢"
        elif clv < -0.05: k = "-10 to -5¢"
        elif clv < 0:    k = "-5 to  0¢"
        elif clv < 0.05: k = "  0 to +5¢"
        elif clv < 0.10: k = " +5 to+10¢"
        else:            k = "     > +10¢"
        b = buckets[k]
        b["n"] += 1
        b["wins"] += 1 if result == "WIN" else 0
        b["pnl"] += pnl
    print(f"  CLV bucket breakdown:")
    print(f"  {'bucket':14}{'n':>5}{'win%':>6}{'avg P&L':>9}")
    order = ["< -10¢", "-10 to -5¢", "-5 to  0¢", "  0 to +5¢", " +5 to+10¢", "     > +10¢"]
    for k in order:
        if k not in buckets: continue
        b = buckets[k]
        wr = b["wins"]/b["n"]*100
        avg_pnl = b["pnl"]/b["n"]
        print(f"  {k:14}{b['n']:>5}{wr:>5.0f}%{avg_pnl:>+9.3f}")

    gate = "PASS ✓" if pos_pct > 55 and n >= 100 else ("UNDERPOWERED" if n < 100 else "FAIL ✗")
    print(f"\n  EXP-006 CLV gate ({window_s}s window): {gate}")
    print()
    return {"n": n, "avg_clv": avg_clv, "pos_pct": pos_pct, "skipped": skipped}


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "auto_house"
    window = int(sys.argv[2]) if len(sys.argv) > 2 else WINDOW_S_DEFAULT
    run(key, window)
