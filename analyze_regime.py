#!/usr/bin/env python3
"""
analyze_regime.py — Per-trade regime breakdown for conviction and auto_house
on the full 246-game backtest corpus.

Tests:
  EXP-002: Do small edges (6-10¢) beat large model gaps (15¢+)? (Large = stale model?)
  EXP-003: Are Q4/final-period entries reliably better than early-game entries?

Pre-registration gate for EXP-004 (time-gated conviction):
  PASS if Q4-only robustness (per_game − 0.5·|worst_game|) > current north-star (0.32)
       AND Q4 win-rate > 55%

    python3 analyze_regime.py                   # conviction
    python3 analyze_regime.py auto_house        # auto_house
"""
import re, sys
from collections import defaultdict
import backtest, strategies as strat, engine


def parse_entry(trade):
    """Extract quarter, seconds-left-in-period, model_p, edge from Trade metadata."""
    m = re.match(r"Q(\d+)\s*([\d:]*)", trade.entry_clock or "")
    quarter = int(m.group(1)) if m else None
    clock_s = None
    if m and m.group(2):
        try:
            parts = m.group(2).split(":")
            clock_s = int(parts[0]) * 60 + float(parts[1])
        except Exception:
            pass
    final_period = quarter is not None and quarter >= 4

    # reason: "TeamName model 82% but priced 73% — buying cheap favorite, holding"
    mp = re.search(r"model\s+(\d+)%", trade.entry_reason or "")
    ap = re.search(r"priced\s+(\d+)%", trade.entry_reason or "")
    model_p = int(mp.group(1)) / 100 if mp else None
    aligned_p = int(ap.group(1)) / 100 if ap else None
    edge = round(model_p - aligned_p, 3) if (model_p is not None and aligned_p is not None) else None
    return dict(quarter=quarter, clock_s=clock_s, final_period=final_period,
                model_p=model_p, aligned_p=aligned_p, edge=edge)


def print_buckets(pairs, key_fn, title, keys_order=None):
    agg = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0, "worst": 0.0})
    for t, m in pairs:
        k = key_fn(m)
        a = agg[k]
        a["n"] += 1
        a["wins"] += 1 if t.result == "WIN" else 0
        a["pnl"] += t.pnl or 0
        a["worst"] = min(a["worst"], t.pnl or 0)
    keys = [k for k in (keys_order or sorted(agg)) if k in agg]
    print(f"\n    {title}")
    print(f"  {'bucket':18}{'n':>5}{'win%':>6}{'total':>9}{'avg/t':>8}{'worst/t':>9}")
    for k in keys:
        a = agg[k]
        wr = a["wins"] / a["n"] * 100 if a["n"] else 0
        avg = a["pnl"] / a["n"] if a["n"] else 0
        print(f"  {str(k):18}{a['n']:>5}{wr:>5.0f}%{a['pnl']:>+9.2f}{avg:>+8.3f}{a['worst']:>+9.2f}")
    return dict(agg)


def run(strategy_key):
    print(f"\nLoading corpus...", flush=True)
    dataset = backtest.load_all()
    print(f"{len(dataset)} games loaded. Simulating {strategy_key}...", flush=True)

    all_pairs = []      # (Trade, meta_dict)
    game_rows = []      # (game_pnl, fp_only_pnl, away, home, date)

    for g, data in dataset:
        meta = engine.parse_ticker(g["ticker"])
        s = strat.make(strategy_key)
        engine.simulate(meta, data, [s])
        trades_with_meta = [(t, parse_entry(t)) for t in s.account.closed]
        all_pairs.extend(trades_with_meta)
        game_pnl = sum(t.pnl or 0 for t in s.account.closed)
        fp_pnl   = sum(t.pnl or 0 for t, em in trades_with_meta if em["final_period"])
        game_rows.append((game_pnl, fp_pnl, g.get("away", "?"), g.get("home", "?"), g.get("date", "?")))

    # ── summary ──
    n = len(all_pairs)
    total_pnl = sum(t.pnl or 0 for t, _ in all_pairs)
    wins = sum(1 for t, _ in all_pairs if t.result == "WIN")
    worst_trade = min((t.pnl or 0) for t, _ in all_pairs) if all_pairs else 0

    print(f"\n{'='*65}")
    print(f"  {strategy_key.upper()} — {len(dataset)} games, {n} trades")
    print(f"{'='*65}")
    print(f"  Total P&L   : {total_pnl:+.2f}  ({total_pnl/len(dataset):+.3f}/game)")
    print(f"  W/L         : {wins}/{n-wins} ({wins/n*100:.0f}%)")
    print(f"  Worst trade : {worst_trade:+.2f}")

    # ── north-star (full strategy) ──
    worst_game_full = min(gp for gp, _, _, _, _ in game_rows) if game_rows else 0
    pg_full = total_pnl / len(dataset)
    ns_full = round(pg_full - 0.5 * abs(worst_game_full), 3)
    print(f"  North-star  : {ns_full:.3f}  (per_game {pg_full:+.3f}, worst_game {worst_game_full:+.3f})")

    # ── by quarter ──
    print_buckets(all_pairs, lambda m: f"Q{m['quarter']}" if m["quarter"] else "?",
                  "By entry quarter",
                  ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "?"])

    # ── final vs. early ──
    print_buckets(all_pairs, lambda m: "Q4+ (final)" if m["final_period"] else "Q1-Q3 (early)",
                  "Final-period vs. early (EXP-003)",
                  ["Q4+ (final)", "Q1-Q3 (early)"])

    # ── seconds left in Q4 ──
    fp_pairs = [(t, m) for t, m in all_pairs if m["final_period"]]
    if fp_pairs:
        def sl_bucket(m):
            s = m["clock_s"]
            if s is None: return "?"
            if s <= 60:  return "≤1min"
            if s <= 180: return "1-3min"
            if s <= 360: return "3-6min"
            return ">6min"
        print_buckets(fp_pairs, sl_bucket,
                      "By time left in Q4 (final-period trades only)",
                      ["≤1min", "1-3min", "3-6min", ">6min", "?"])

    # ── edge size (EXP-002) ──
    def edge_bucket(m):
        e = m["edge"]
        if e is None: return "?"
        if e < 0.08:  return "6-8¢"
        if e < 0.12:  return "8-12¢"
        if e < 0.15:  return "12-15¢"
        return "15¢+"
    print_buckets(all_pairs, edge_bucket,
                  "By model edge at entry (EXP-002: small > large?)",
                  ["6-8¢", "8-12¢", "12-15¢", "15¢+", "?"])

    # ── model probability at entry ──
    def prob_bucket(m):
        p = m["model_p"]
        if p is None: return "?"
        if p < 0.75: return "70-75%"
        if p < 0.80: return "75-80%"
        if p < 0.85: return "80-85%"
        return "85%+"
    print_buckets(all_pairs, prob_bucket,
                  "By model probability at entry",
                  ["70-75%", "75-80%", "80-85%", "85%+", "?"])

    # ── worst games (full strategy) ──
    print(f"\n    Worst 10 games:")
    print(f"  {'P&L':>8}  {'date':>10}  {'matchup':22}  notes")
    for gp, fp, away, home, dt in sorted(game_rows)[:10]:
        non_fp = round(gp - fp, 2)
        note = f"early={non_fp:+.2f}  Q4={fp:+.2f}"
        print(f"  {gp:>+8.2f}  {dt}  {away:>4}@{home:<17}  {note}")

    # ── Q4-only north-star estimate (EXP-004 gate) ──
    fp_game_pnl = [fp for _, fp, _, _, _ in game_rows]
    fp_pg = sum(fp_game_pnl) / len(dataset)
    fp_worst_game = min(fp_game_pnl)
    fp_ns = round(fp_pg - 0.5 * abs(fp_worst_game), 3)
    fp_trades = len(fp_pairs)
    fp_wins = sum(1 for t, _ in fp_pairs if t.result == "WIN")
    fp_wr = fp_wins / fp_trades * 100 if fp_trades else 0
    games_with_fp = sum(1 for p in fp_game_pnl if p != 0)

    print(f"\n{'='*65}")
    print(f"  EXP-004 GATE: Q4-only conviction (final_period entries only)")
    print(f"  PASS if north-star > 0.32 AND win-rate > 55%")
    print(f"{'='*65}")
    print(f"  Q4 trades        : {fp_trades} trades, {games_with_fp}/{len(dataset)} games active")
    print(f"  Q4 win-rate      : {fp_wr:.0f}%  (gate: >55%)")
    print(f"  Q4 per-game P&L  : {fp_pg:+.3f}")
    print(f"  Q4 worst game    : {fp_worst_game:+.3f}")
    print(f"  Q4 north-star    : {fp_ns:.3f}  (gate: >0.32)  {'PASS ✓' if fp_ns > 0.32 else 'FAIL ✗'}")
    verdict = "PASS" if (fp_ns > 0.32 and fp_wr > 55) else "FAIL"
    print(f"\n  → EXP-004 gate: {verdict}")
    print()

    return all_pairs, game_rows, {"fp_ns": fp_ns, "fp_wr": fp_wr, "full_ns": ns_full}


if __name__ == "__main__":
    keys = sys.argv[1:] or ["conviction"]
    for k in keys:
        run(k)
