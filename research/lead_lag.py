#!/usr/bin/env python3
"""
lead_lag.py — EXP-009: is there a LIVE intra-game lead-lag we could trade?

The pre-game/settlement avenues are dead. The one untested mechanism: during a game, when
a scoring play moves win-prob, does the Kalshi PRICE reprice with a lag — leaving a window?
Tested on captured live games (tick-level Kalshi mid + ESPN win-prob, timestamped).

Two things decide if it's tradeable FOR US:
  1. Direction of lead-lag: does win-prob CHANGE lead the mid change (window exists) or
     follow it (price already moved — nothing to catch)? Cross-correlation over ±lag.
  2. Our budget: we learn win-prob from ESPN's ~5s poll; Kalshi reprices from its own faster
     feed. If the price leads our signal, we can't beat it. The event study shows when the
     mid actually moves relative to the win-prob jump.

    python3 research/lead_lag.py
"""
import glob, json, os, sys, statistics as st
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine                                            # noqa: E402

GAMES = os.path.join(ROOT, "data", "games")
OUT = os.path.join(ROOT, "docs", "LEAD_LAG.md")


def _read(path):
    rows = []
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def grid_for(gdir):
    """Per-second forward-filled (mid_yes, winprob_yes) grid for one captured game."""
    meta_f = os.path.join(gdir, "meta.json")
    ticker = None
    if os.path.exists(meta_f):
        try:
            ticker = json.load(open(meta_f)).get("ticker")
        except Exception:
            pass
    ticker = ticker or os.path.basename(gdir)
    meta = engine.parse_ticker(ticker)
    if not meta:
        return None
    yih = meta["yes_is_home"]
    pts = []
    for t in _read(os.path.join(gdir, "ticks.jsonl")):
        ts = engine._iso_to_unix(t.get("ts"))
        m = (t.get("market") or {}).get("mid")
        wph = (t.get("game") or {}).get("win_prob_home")
        if ts is None:
            continue
        wp_yes = None if wph is None else (wph if yih else 1 - wph)
        pts.append((ts, m, wp_yes))
    pts.sort(key=lambda x: x[0])
    if len(pts) < 60:
        return None
    lo, hi = int(pts[0][0]), int(pts[-1][0])
    if hi - lo > 6 * 3600:               # guard against stray ts
        hi = lo + 6 * 3600
    grid, mid, wp, j = [], None, None, 0
    for s in range(lo, hi + 1):
        while j < len(pts) and pts[j][0] <= s:
            if pts[j][1] is not None: mid = pts[j][1]
            if pts[j][2] is not None: wp = pts[j][2]
            j += 1
        if mid is not None and wp is not None:
            grid.append((s, mid, wp))
    return grid


def main():
    grids = []
    for d in sorted(glob.glob(os.path.join(GAMES, "*"))):
        if os.path.isdir(d):
            g = grid_for(d)
            if g and len(g) > 300:
                grids.append((os.path.basename(d), g))
    if not grids:
        print("no usable captured games"); return

    # cross-correlation of per-second changes: corr(Δwp[t], Δmid[t+lag]) for lag in -8..+8.
    # lag>0 ⇒ mid moves AFTER wp (win-prob leads → window). lag<0 ⇒ price leads (no window).
    LAGS = list(range(-8, 9))
    paired = defaultdict(list)            # lag -> [(dwp, dmid)]
    events = []                           # (game, [Δmid per second from -10..+10 around a wp jump])
    for name, g in grids:
        dwp = [g[i][2] - g[i - 1][2] for i in range(1, len(g))]
        dmid = [g[i][1] - g[i - 1][1] for i in range(1, len(g))]
        for lag in LAGS:
            for t in range(len(dwp)):
                u = t + lag
                if 0 <= u < len(dmid):
                    paired[lag].append((dwp[t], dmid[u]))
        # event study around big win-prob jumps
        for t in range(11, len(g) - 11):
            jump = g[t][2] - g[t - 1][2]
            if abs(jump) >= 0.03:
                sgn = 1 if jump > 0 else -1
                # cumulative mid move (signed by jump dir) from t-10..t+10 relative to t
                base = g[t - 1][1]
                events.append([sgn * (g[t + k][1] - base) for k in range(-10, 11)])

    def corr(pairs):
        if len(pairs) < 30: return None
        xs = [a for a, _ in pairs]; ys = [b for _, b in pairs]
        mx, my = st.mean(xs), st.mean(ys)
        num = sum((a - mx) * (b - my) for a, b in pairs)
        dx = sum((a - mx) ** 2 for a in xs) ** 0.5; dy = sum((b - my) ** 2 for b in ys) ** 0.5
        return num / (dx * dy) if dx and dy else None

    corrs = {lag: corr(paired[lag]) for lag in LAGS}
    best_lag = max((l for l in LAGS if corrs[l] is not None), key=lambda l: corrs[l])

    L = ["# LEAD-LAG — EXP-009: is there a tradeable live intra-game lag?",
         f"\n_`research/lead_lag.py`. {len(grids)} captured games, per-second grid of Kalshi mid "
         "vs ESPN win-prob (both yes-space). Cross-corr of changes: lag>0 ⇒ price moves AFTER "
         "win-prob (a window for us); lag<0 ⇒ price LEADS our signal (we can't catch it)._\n",
         "## Cross-correlation: corr(Δwin-prob[t], Δmid[t+lag])",
         "| lag (s) | corr |", "|---|---|"]
    for lag in LAGS:
        c = corrs[lag]
        L.append(f"| {lag:+d} | {c:+.3f} |" if c is not None else f"| {lag:+d} | — |")
    L.append("")
    L.append(f"**Peak correlation at lag = {best_lag:+d}s "
             f"({'win-prob leads price — POTENTIAL window' if best_lag > 0 else 'price leads/coincident — no exploitable window for us' if best_lag <= 0 else ''}).**")
    if events:
        n = len(events)
        avg = [st.mean(e[k] for e in events) for k in range(21)]
        L += ["", f"## Event study — avg signed mid move around {n} win-prob jumps (≥3¢)",
              "_second 0 = the win-prob jump; values = cumulative mid move in the jump's "
              "direction (¢). If the price already moved by second 0, it leads us._", "",
              "| sec rel to wp jump | -5 | -2 | 0 | +1 | +2 | +5 | +10 |",
              "|---|---|---|---|---|---|---|---|",
              f"| cum mid move ¢ | {avg[5]*100:+.1f} | {avg[8]*100:+.1f} | {avg[10]*100:+.1f} | "
              f"{avg[11]*100:+.1f} | {avg[12]*100:+.1f} | {avg[15]*100:+.1f} | {avg[20]*100:+.1f} |"]
        moved_by_0 = avg[10]; moved_after = avg[12] - avg[10]
        L += ["", f"**By the jump (sec 0) the price has already moved {moved_by_0*100:+.1f}¢; "
              f"the additional move in the +2s we could act in is {moved_after*100:+.1f}¢.** "
              "(Remember: we only LEARN of the jump via ESPN's ~5s poll — so even a positive "
              "+2s move isn't ours unless it persists past our signal+exec latency.)"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(L) + "\n")
    print(f"Wrote {OUT}")
    print(f"  {len(grids)} games · peak corr lag {best_lag:+d}s · "
          f"corr@0={corrs.get(0)} corr@+2={corrs.get(2)} corr@-2={corrs.get(-2)}")
    if events:
        print(f"  event study ({len(events)} jumps): moved by sec0 {avg[10]*100:+.1f}¢, "
              f"extra by +2s {(avg[12]-avg[10])*100:+.1f}¢")


if __name__ == "__main__":
    main()
