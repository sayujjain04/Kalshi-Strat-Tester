#!/usr/bin/env python3
"""
market_making.py — EXP-010: would passive market-making (spread capture) make money?

The one mechanism that works in an EFFICIENT market: don't predict, quote both sides and
earn the bid-ask spread — a small edge per fill, scaled by size (the founder's thesis).
Its enemy is ADVERSE SELECTION: you get filled right before the price moves against you.

Estimated from captured games (trades.jsonl = taker fills; ticks.jsonl = mid trajectory).
For each taker trade, WE are the maker on the other side:
  - taker bought YES at P  → we SOLD yes at P (short). realized = P − mid(t+Δ)
  - taker sold  YES at P  → we BOUGHT yes at P (long).  realized = mid(t+Δ) − P
`realized spread` = half-spread earned − adverse selection. Net = realized − maker fee.
MM is viable iff mean net per contract > 0 (then unit size scales it).

    python3 research/market_making.py
"""
import glob, json, os, sys, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine                                            # noqa: E402

GAMES = os.path.join(ROOT, "data", "games")
OUT = os.path.join(ROOT, "docs", "MARKET_MAKING.md")
FEE_K = 0.07


def _read(path):
    out = []
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def mid_series(gdir):
    pts = []
    for t in _read(os.path.join(gdir, "ticks.jsonl")):
        ts = engine._iso_to_unix(t.get("ts"))
        m = (t.get("market") or {})
        if ts is not None and m.get("mid") is not None:
            pts.append((ts, m["mid"], m.get("yes_bid"), m.get("yes_ask")))
    pts.sort()
    return pts


def mid_at(pts, ts):
    """last mid at/just after ts (linear-ish: nearest tick with ts' >= ts, else last)."""
    lo, hi = 0, len(pts) - 1
    if not pts:
        return None
    # binary search first tick with ts' >= ts
    import bisect
    i = bisect.bisect_left([p[0] for p in pts], ts)
    if i >= len(pts):
        i = len(pts) - 1
    return pts[i][1]


def analyze(delta_s=30):
    rows = []   # (realized, fee, count)
    spreads = []
    games_used = 0
    for d in sorted(glob.glob(os.path.join(GAMES, "*"))):
        if not os.path.isdir(d):
            continue
        pts = mid_series(d)
        trades = _read(os.path.join(d, "trades.jsonl"))
        if len(pts) < 60 or len(trades) < 200:
            continue
        # spreads from ticks (context)
        for _, _, yb, ya in pts:
            if yb is not None and ya is not None and ya > yb:
                spreads.append(ya - yb)
        ts_list = [p[0] for p in pts]
        seen = set()
        used = 0
        import bisect
        for tr in trades:
            ms = tr.get("ts_ms")
            P = tr.get("price")
            cnt = tr.get("count") or tr.get("count_fp") or 1
            side = tr.get("taker_side")
            if ms is None or P is None or side not in ("yes", "no"):
                continue
            key = (ms, P, cnt, side)             # dedup (trades.jsonl had a re-append bug)
            if key in seen:
                continue
            seen.add(key)
            ts = ms / 1000.0
            mid_fut = mid_at(pts, ts + delta_s)
            if mid_fut is None:
                continue
            P = float(P); cnt = float(cnt)
            if side == "yes":                    # taker bought yes → maker sold yes at P (short)
                realized = P - mid_fut
            else:                                # taker sold yes → maker bought yes at P (long)
                realized = mid_fut - P
            fee = FEE_K * P * (1 - P)             # maker fee per contract (conservative: same as taker)
            rows.append((realized, fee, cnt))
            used += 1
        if used:
            games_used += 1
    return rows, spreads, games_used


def main():
    results = {}
    for delta in (30, 60):
        rows, spreads, ng = analyze(delta)
        if not rows:
            continue
        # contract-weighted means
        tot_c = sum(c for _, _, c in rows)
        realized = sum(r * c for r, _, c in rows) / tot_c
        fee = sum(f * c for _, f, c in rows) / tot_c
        net = realized - fee
        pos = sum(c for r, f, c in rows if (r - f) > 0) / tot_c
        results[delta] = {"n_fills": len(rows), "contracts": tot_c, "games": ng,
                          "realized": realized, "fee": fee, "net": net, "pos": pos,
                          "spread_med": st.median(spreads) if spreads else None}

    L = ["# MARKET MAKING — EXP-010: does passive spread capture pay?",
         "\n_`research/market_making.py`. Captured games; for each taker fill WE are the maker on "
         "the other side. realized spread = half-spread earned − adverse selection (mid move "
         "against us over Δ); net = realized − maker fee. Contract-weighted. >0 net = scalable._\n"]
    sm = next(iter(results.values()), {}).get("spread_med")
    if sm is not None:
        L.append(f"- Median quoted spread (ask−bid): **{sm*100:.1f}¢** — the most a maker at the "
                 f"touch could gross per round-trip before adverse selection + fees.\n")
    L += ["| hold Δ | fills | contracts | realized spread ¢ | maker fee ¢ | **net ¢/contract** | % fills net+ |",
          "|---|---|---|---|---|---|---|"]
    for delta, r in results.items():
        L.append(f"| {delta}s | {r['n_fills']:,} | {r['contracts']:,.0f} | {r['realized']*100:+.2f} | "
                 f"{r['fee']*100:.2f} | **{r['net']*100:+.2f}** | {r['pos']*100:.0f}% |")
    v = results.get(30) or next(iter(results.values()), None)
    if v:
        if v["net"] > 0:
            verdict = (f"Net **{v['net']*100:+.2f}¢/contract** — POSITIVE. Spread capture clears "
                       "adverse selection + fees; this is a scalable structural edge worth building "
                       "(quote engine + inventory/risk).")
        else:
            verdict = (f"Net **{v['net']*100:+.2f}¢/contract** — NEGATIVE. Adverse selection + the "
                       f"maker fee ({v['fee']*100:.2f}¢) exceed the realized spread; passive MM loses "
                       "on this market. (Kalshi's per-fill fee vs a ~1-2¢ spread is the likely killer.)")
        L += ["", f"**Verdict: {verdict}**"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(L) + "\n")
    print(f"Wrote {OUT}")
    for delta, r in results.items():
        print(f"  Δ{delta}s: realized {r['realized']*100:+.2f}¢  fee {r['fee']*100:.2f}¢  "
              f"NET {r['net']*100:+.2f}¢/contract  ({r['pos']*100:.0f}% fills net+, {r['n_fills']:,} fills, {r['games']} games)")
    if v:
        print(f"  median spread: {v['spread_med']*100:.1f}¢")


if __name__ == "__main__":
    main()
