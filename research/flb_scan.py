#!/usr/bin/env python3
"""
research/flb_scan.py — Favorite-Longshot Bias (FLB) / Calibration scan.

Tests whether Kalshi in-game prices at various time windows before settlement
are well-calibrated, or exhibit systematic over/under-pricing at specific
probability ranges (the classic FLB).

Academic prior: in sportsbooks, FLB means favorites are UNDERPRICED
(longshots over-priced). In liquid prediction markets like Kalshi, the
direction may differ. Our holdout note (2026-05-27) hinted the 0.4-0.9
band was OVER-priced (reverse FLB) in playoffs. This scan tests that
rigorously on the full 305-game corpus.

EXP-012 pre-registration (see experiments.jsonl).

Usage:
    python3 research/flb_scan.py
"""
import gzip
import json
import os
import math
from collections import defaultdict

DATA_DIR = "data/backtest"
OFFSETS_MIN = [15, 30, 60, 120]   # minutes before last candle


def load_games():
    games = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".json.gz"):
            continue
        path = os.path.join(DATA_DIR, fn)
        with gzip.open(path) as f:
            raw = json.load(f)
        g = raw["g"]
        candles = raw["data"].get("candles", [])
        if len(candles) < 10:
            continue
        games.append((g, sorted(candles, key=lambda c: c["ts"])))
    return games


def get_outcome(candles):
    """YES team won if last candle price >= 0.50."""
    return 1 if candles[-1]["c"] >= 0.50 else 0


def price_at_offset(candles, offset_min):
    """
    Kalshi mid (close price) at approximately (last_ts - offset_min * 60).
    Returns None if no candle within 90 seconds of that target.
    """
    last_ts = candles[-1]["ts"]
    target_ts = last_ts - offset_min * 60
    best_c, best_diff = None, float("inf")
    for c in candles:
        diff = abs(c["ts"] - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_c = c
    if best_diff > 120:
        return None
    return best_c["c"]


def bucket_label(p):
    bounds = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    for i, upper in enumerate(bounds):
        if p < upper:
            lo = 0.01 if i == 0 else bounds[i - 1]
            return f"{lo:.2f}-{upper:.2f}"
    return "0.90-0.99"


BUCKET_ORDER = [
    "0.01-0.10", "0.10-0.20", "0.20-0.30", "0.30-0.40", "0.40-0.50",
    "0.50-0.60", "0.60-0.70", "0.70-0.80", "0.80-0.90", "0.90-0.99",
]


def wilson_ci(wins, n, z=1.96):
    """95% Wilson confidence interval for a proportion."""
    if n == 0:
        return 0.0, 1.0
    p_hat = wins / n
    denom = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denom
    return max(0, centre - margin), min(1, centre + margin)


def run_scan(offset_min, games, league_filter=None):
    label = f"T-{offset_min}min" + (f" [{league_filter}]" if league_filter else "")
    buckets = defaultdict(lambda: {"n": 0, "wins": 0, "prices": []})

    for g, candles in games:
        league = g.get("league", "NBA")
        if league_filter and league != league_filter:
            continue
        price = price_at_offset(candles, offset_min)
        if price is None or price < 0.01 or price > 0.99:
            continue
        outcome = get_outcome(candles)

        # Treat both YES and NO perspectives symmetrically:
        # The price 'p' IS the YES implied win prob, outcome IS whether YES won.
        # That's the calibration test.
        k = bucket_label(price)
        buckets[k]["n"] += 1
        buckets[k]["wins"] += outcome
        buckets[k]["prices"].append(price)

    total_n = sum(b["n"] for b in buckets.values())
    if total_n == 0:
        return {}

    print(f"\n{'='*70}")
    print(f"  FLB CALIBRATION — {label}  ({total_n} game-samples)")
    print(f"{'='*70}")
    print(f"  {'bucket':12} {'n':>4} {'avg_p':>7} {'win_rt':>7} {'bias':>7} {'95%CI':>14} {'sig':>4}")
    print(f"  {'-'*65}")

    results = {}
    for k in BUCKET_ORDER:
        if k not in buckets:
            continue
        b = buckets[k]
        n = b["n"]
        avg_p = sum(b["prices"]) / n
        win_rt = b["wins"] / n
        bias = win_rt - avg_p   # + = market underpriced (favorites), - = overpriced
        lo, hi = wilson_ci(b["wins"], n)
        bias_ci = f"[{lo-avg_p:+.2f},{hi-avg_p:+.2f}]"
        # Significant if the CI for win_rt excludes avg_p
        sig = "*" if (lo > avg_p or hi < avg_p) and n >= 15 else " "
        print(f"  {k:12} {n:>4} {avg_p:>7.3f} {win_rt:>7.3f} {bias:>+7.3f} {bias_ci:>14} {sig:>4}")
        results[k] = {"n": n, "avg_p": avg_p, "win_rt": win_rt, "bias": bias, "lo": lo, "hi": hi}

    # Summary: systematic directional bias across all buckets
    # Weighted by n
    total_w = sum(r["n"] for r in results.values())
    if total_w:
        weighted_bias = sum(r["bias"] * r["n"] for r in results.values()) / total_w
        print(f"\n  Weighted avg bias: {weighted_bias:+.4f} ({weighted_bias*100:+.2f}c/contract)")
        # Look for actionable buckets
        signals = [
            (k, r) for k, r in results.items()
            if r["n"] >= 20 and abs(r["bias"]) > 0.05
            and (r["lo"] > r["avg_p"] or r["hi"] < r["avg_p"])
        ]
        if signals:
            print(f"\n  ** POTENTIAL SIGNALS (n>=20, |bias|>5c, CI excludes avg_p):")
            for k, r in signals:
                direction = "FADE (buy NO)" if r["bias"] < 0 else "FOLLOW (buy YES)"
                print(f"     {k}: avg_p={r['avg_p']:.3f} win_rt={r['win_rt']:.3f} "
                      f"bias={r['bias']:+.3f} → {direction}")
        else:
            print("  No significant actionable signals in this window.")

    return results


if __name__ == "__main__":
    print("Loading backtest corpus...")
    games = load_games()
    print(f"  Loaded {len(games)} games")

    # League breakdown
    nba = [(g, c) for g, c in games if g.get("league") == "NBA"]
    wnba = [(g, c) for g, c in games if g.get("league") == "WNBA"]
    print(f"  NBA: {len(nba)}  WNBA: {len(wnba)}")

    # Full corpus scans at multiple time windows
    print("\n\n[FULL CORPUS - ALL LEAGUES]")
    for offset in OFFSETS_MIN:
        run_scan(offset, games)

    # League splits
    if wnba:
        print("\n\n[WNBA ONLY]")
        for offset in [15, 30]:
            run_scan(offset, games, league_filter="WNBA")

    if nba:
        print("\n\n[NBA ONLY]")
        for offset in [15, 30]:
            run_scan(offset, games, league_filter="NBA")

    print("\n\nDone.")
