#!/usr/bin/env python3
"""
edge_discovery.py — MINE THE CORPUS FOR EDGE, don't tune heuristics and hope.

For every play of every corpus game we have an aligned triple:
    (ESPN win-prob, Kalshi YES mid at that instant, eventual settlement)
plus regime context (time left, who's favored, lead size, order flow). That's
~118k observations the lab was never using. This script asks the only questions
that matter before any strategy is worth writing:

  1. CALIBRATION — is the Kalshi mid sharp? is ESPN win-prob sharp? WHO IS SHARPER,
     and in which regime? (Brier + reliability, market vs model.) If neither beats
     the other out-of-sample, there is no predictive edge → chase only STRUCTURAL
     edge (fees/settlement) and stop pretending.

  2. MISPRICING SCAN — where the model–market gap predicts settlement better than
     the price implies, that gap IS the edge. Slice by gap × time × favorite band.
     But rigor, baked in so we don't fool ourselves:
       · the statistical unit is the GAME, not the play (plays inside a game are
         one correlated bet) → require enough GAMES per cell, not just rows;
       · fill at the bid/ask we'd actually CROSS (hold-to-settlement), not the mid;
       · FRESHNESS guard — drop observations whose price bar is stale (else a fresh
         win-prob "beats" a price you could never have traded — the clutch artifact);
       · every finding re-measured on a strictly later holdout (time-split). Big
         decay = overfit = killed.

A regime that clears fees in BOTH halves, with enough games and a mechanism, becomes
a pre-registered strategy. Hypothesis generation with the rigor up front. Run:

    python3 research/edge_discovery.py            # full scan → docs/EDGE_SCAN.md
    python3 research/edge_discovery.py --league WNBA
"""
import bisect, glob, gzip, json, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine                                            # noqa: E402

CORPUS = os.path.join(ROOT, "data", "backtest")
OUT = os.path.join(ROOT, "docs", "EDGE_SCAN.md")

LEAGUE_CLOCK = {"NBA": (4, 720), "WNBA": (4, 600), "NCAAM": (2, 1200),
                "NCAAW": (4, 600), "NCAA": (2, 1200)}
FEE_K = 0.07            # Kalshi fee coefficient; hold-to-settlement = 1 leg (entry only)
FRESH_S = 90           # max age (s) of the price bar at decision time — else stale, drop
MIN_GAMES = 12         # a cell needs this many distinct games before we trust it


def _clock_secs(clock):
    s = str((clock or {}).get("displayValue", "")).strip()
    if not s:
        return None
    try:
        if ":" in s:
            mm, ss = s.split(":")
            return int(mm) * 60 + float(ss)
        return float(s)
    except Exception:
        return None


def _secs_left(play, league):
    nper, plen = LEAGUE_CLOCK.get(league, LEAGUE_CLOCK["NBA"])
    per = (play.get("period") or {}).get("number") or 1
    inper = _clock_secs(play.get("clock"))
    if inper is None:
        return None
    if per > nper:
        return max(0.0, inper)
    return max(0.0, (nper - per) * plen + inper)


def _candle_at(candles, t):
    """Last candle ENDING ≤ t (no look-ahead) — full bar (mid + bid/ask + age)."""
    out = None
    for c in candles:
        ts = c.get("ts")
        if ts is not None and t >= ts and c.get("c") is not None:
            out = c
        elif ts is not None and ts > t:
            break
    return out


def _flow_at(flow_ends, flow, t):
    if not flow_ends:
        return 0.0
    j = bisect.bisect_right(flow_ends, t) - 1
    return flow[j][1] if j >= 0 else 0.0


def observations(league_filter=None):
    obs = []
    for p in sorted(glob.glob(os.path.join(CORPUS, "*.json.gz"))):
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        g, data = rec.get("g", {}), rec.get("data", {})
        league = g.get("league", "NBA")
        if league_filter and league != league_filter:
            continue
        meta = engine.parse_ticker(g.get("ticker", ""))
        if not meta:
            continue
        gid = os.path.basename(p).replace(".json.gz", "")
        plays = data.get("plays") or []
        wp_by_id = data.get("wp_by_id") or {}
        candles = data.get("candles") or []
        flow = data.get("flow") or []
        flow_ends = [b[0] + 30 for b in flow]
        last = plays[-1] if plays else {}
        yes_won = engine._settle_yes(
            data.get("kalshi_result"),
            {"home": last.get("homeScore"), "away": last.get("awayScore")},
            meta["yes_is_home"])
        if yes_won is None:
            continue
        yih = meta["yes_is_home"]
        for pl in plays:
            wph = wp_by_id.get(pl.get("id"))
            if wph is None:
                continue
            t = engine._iso_to_unix(pl.get("wallclock"))
            if t is None:
                continue
            c = _candle_at(candles, t)
            if not c:
                continue
            mid = c["c"]
            yb = c.get("yb") if c.get("yb") else max(0.0, mid - 0.005)
            ya = c.get("ya") if c.get("ya") else min(1.0, mid + 0.005)
            hs, as_ = pl.get("homeScore"), pl.get("awayScore")
            margin = (hs - as_) if (hs is not None and as_ is not None) else None
            if margin is not None and not yih:
                margin = -margin
            obs.append({
                "gid": gid, "date": g.get("date", ""), "league": league,
                "model": float(wph if yih else 1 - wph), "market": float(mid),
                "yb": float(yb), "ya": float(ya),
                "stale": (t - c["ts"]) if c.get("ts") else 1e9,
                "secs_left": _secs_left(pl, league), "margin": margin,
                "flow": _flow_at(flow_ends, flow, t),
                "yes_won": 1 if yes_won else 0,
            })
    return obs


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps) if ps else None


def reliability(ps, ys, edges=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.01)):
    rows = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        sel = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi]
        if sel:
            rows.append((lo, hi, len(sel),
                         sum(p for p, _ in sel) / len(sel),
                         sum(y for _, y in sel) / len(sel)))
    return rows


def calibration_block(obs, label):
    m_p = [o["market"] for o in obs]
    g_p = [o["model"] for o in obs]
    ys = [o["yes_won"] for o in obs]
    bm, bg = brier(m_p, ys), brier(g_p, ys)
    L = [f"### Calibration — {label}  (n={len(obs):,} plays)",
         f"- **Brier (lower=sharper): Kalshi mid {bm:.4f}  ·  ESPN WP {bg:.4f}** → "
         f"{'MARKET sharper' if bm < bg else 'ESPN WP sharper'} by {abs(bm-bg):.4f}",
         "", "| pred band | n | realized | mkt mean | espn mean |",
         "|---|---|---|---|---|"]
    rel_g = {(lo, hi): (mp, rl) for lo, hi, n, mp, rl in reliability(g_p, ys)}
    for lo, hi, n, mp, rl in reliability(m_p, ys):
        gp = rel_g.get((lo, hi))
        L.append(f"| {lo:.1f}–{hi:.1f} | {n:,} | {rl:.3f} | {mp:.3f} | "
                 f"{gp[0]:.3f} |" if gp else
                 f"| {lo:.1f}–{hi:.1f} | {n:,} | {rl:.3f} | {mp:.3f} | — |")
    L.append("")
    return L, (bm, bg)


def _hurdle(price):
    return FEE_K * price * (1 - price)          # 1 leg — buy then hold to free settlement


def mispricing_scan(obs, label):
    """Bucket by gap (model−mid) × time. Signal on mid; FILL on the ask/bid we'd cross,
    held to settlement. Aggregate by GAME (the real unit), then average across games."""
    def time_bucket(s):
        if s is None: return "?"
        if s > 1800: return "1_early(>30m)"
        if s > 600:  return "2_mid(10-30m)"
        if s > 120:  return "3_late(2-10m)"
        return "4_clutch(<2m)"

    def gap_bucket(g):
        a, sign = abs(g), ("+" if g > 0 else "-")
        if a < .03: return None
        if a < .06: return f"{sign}3-6c"
        if a < .10: return f"{sign}6-10c"
        if a < .18: return f"{sign}10-18c"
        return f"{sign}18c+"

    # cell -> game -> [net payoffs]; net = (realized − fill_price) − hurdle, hold to settle
    cells = defaultdict(lambda: defaultdict(list))
    for o in obs:
        if o["stale"] > FRESH_S:                 # price bar too old → not tradeable, drop
            continue
        gap = o["model"] - o["market"]
        gb = gap_bucket(gap)
        if gb is None:
            continue
        tb = time_bucket(o["secs_left"])
        if gap > 0:                              # model says YES underpriced → buy YES @ ask
            fill = o["ya"]; payoff = o["yes_won"] - fill
        else:                                    # buy NO @ no-ask (=1−yes_bid)
            fill = 1 - o["yb"]; payoff = (1 - o["yes_won"]) - fill
        net = payoff - _hurdle(fill)
        cells[(tb, gb)][o["gid"]].append(net)

    rows = []
    for (tb, gb), bygame in cells.items():
        if len(bygame) < MIN_GAMES:
            continue
        game_means = [sum(v) / len(v) for v in bygame.values()]
        edge = sum(game_means) / len(game_means)     # mean across games (clustered)
        n_obs = sum(len(v) for v in bygame.values())
        wins = sum(1 for gm in game_means if gm > 0)
        rows.append({"time": tb, "gap": gb, "games": len(bygame), "n": n_obs,
                     "net_edge": edge, "game_winrate": wins / len(game_means)})
    rows.sort(key=lambda r: -r["net_edge"])
    L = [f"### Mispricing scan — {label}",
         "Net ¢ = realized settlement − ask/bid you'd cross − fee, **averaged across "
         f"games** (the real unit; cells need ≥{MIN_GAMES} games and a fresh price bar "
         f"≤{FRESH_S}s). Positive net = candidate edge.", "",
         "| time | gap (model−mid) | games | net ¢ | game-win% |",
         "|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['time']} | {r['gap']} | {r['games']} | "
                 f"**{r['net_edge']*100:+.1f}** | {r['game_winrate']*100:.0f}% |")
    L.append("")
    return L, rows


FLOW_OUT = os.path.join(ROOT, "docs", "FLOW_SCAN.md")


def _mid_after(candles, t):
    """(mid, yb, ya) of the first candle ENDING > t — the de-leaked price you could
    transact at once you've observed everything up to t (same anti-look-ahead rule as
    engine.fill_candle)."""
    for c in candles:
        if c.get("ts") and c["ts"] > t and c.get("c") is not None:
            yb = c.get("yb") or max(0.0, c["c"] - 0.005)
            ya = c.get("ya") or min(1.0, c["c"] + 0.005)
            return c["c"], yb, ya
    return None, None, None


def flow_forward_scan(league=None, horizons=(30, 60, 120)):
    """EXP-006: does signed order-flow predict the NEXT price move? For each enriched flow
    bucket [ts,net,vol,px,n,max,big], decide at bucket CLOSE (net flow only known then),
    enter at the de-leaked mid, and measure the forward mid move IN THE FLOW'S DIRECTION
    over each horizon. GROSS = does flow predict direction at all (signal). NET = after the
    round-trip cost you'd actually pay (cross the spread twice + 2 fees) — the tradeable
    bar, which is HIGH because this is a round trip, not a hold-to-free-settlement.
    Game-clustered (one game = one bet), OOS time-split."""
    def strength(net):
        a = abs(net)
        if a < 50:   return None              # below informative threshold
        if a < 200:  return "1_flow50-200"
        if a < 1000: return "2_flow200-1k"
        return "3_flow1k+"

    games = []
    for p in sorted(glob.glob(os.path.join(CORPUS, "*.json.gz"))):
        try:
            rec = json.load(gzip.open(p, "rt", encoding="utf-8"))
        except Exception:
            continue
        g, d = rec.get("g", {}), rec.get("data", {})
        if league and g.get("league") != league:
            continue
        fl = d.get("flow") or []
        cs = sorted((c for c in (d.get("candles") or []) if c.get("ts")), key=lambda c: c["ts"])
        if not fl or len(fl[0]) < 7 or len(cs) < 5:
            continue
        games.append((os.path.basename(p).replace(".json.gz", ""), g.get("date", ""), cs, fl))
    games.sort(key=lambda x: (x[1], x[0]))
    gids = [g[0] for g in games]
    split = set(gids[: int(len(gids) * 0.6)])

    def scan(subset):
        # cell -> game -> {gross:[], net:[]}
        cells = defaultdict(lambda: defaultdict(lambda: {"gross": [], "net": []}))
        for gid, date, cs, fl in subset:
            for b in fl:
                bt, net = b[0], b[1]
                st = strength(net)
                if st is None:
                    continue
                mid0, yb0, ya0 = _mid_after(cs, bt + 30)        # decide at bucket close
                if mid0 is None:
                    continue
                spread = max(0.0, ya0 - yb0)
                hurdle = spread + 2 * _hurdle(mid0)             # round trip: 2 crossings+fees
                for h in horizons:
                    midh, _, _ = _mid_after(cs, bt + 30 + h)
                    if midh is None:
                        continue
                    gross = (midh - mid0) * (1 if net > 0 else -1)
                    cells[(h, st)][gid]["gross"].append(gross)
                    cells[(h, st)][gid]["net"].append(gross - hurdle)
        rows = []
        for (h, st), bygame in cells.items():
            if len(bygame) < MIN_GAMES:
                continue
            g_means = [sum(v["gross"]) / len(v["gross"]) for v in bygame.values()]
            n_means = [sum(v["net"]) / len(v["net"]) for v in bygame.values()]
            rows.append({"h": h, "st": st, "games": len(bygame),
                         "gross": sum(g_means) / len(g_means),
                         "net": sum(n_means) / len(n_means),
                         "gross_pos": sum(1 for x in g_means if x > 0) / len(g_means)})
        return {(r["h"], r["st"]): r for r in rows}

    disc = scan([g for g in games if g[0] in split])
    hold = scan([g for g in games if g[0] not in split])

    L = ["# FLOW SCAN — EXP-006: does order-flow predict the next price move?",
         f"\n_`research/edge_discovery.py --flow`. {len(games)} games"
         f"{f' ({league})' if league else ''} with enriched flow. Decide at each 30s flow "
         "bucket's close, enter de-leaked, measure forward mid move in the flow's direction. "
         "Game-clustered; 60/40 OOS time-split._\n",
         "> GROSS = does flow predict direction (signal, ignoring cost). NET = after the "
         "round-trip you'd actually pay (2× spread + 2 fees) — the real tradeable bar. "
         "A real edge needs GROSS>0 in BOTH halves AND NET>0.\n",
         "| horizon | flow strength | games(d/h) | GROSS disc ¢ | GROSS hold ¢ | gross+% | NET disc ¢ | NET hold ¢ |",
         "|---|---|---|---|---|---|---|---|"]
    for key in sorted(disc, key=lambda k: (k[0], k[1])):
        d, h = disc[key], hold.get(key)
        L.append(f"| {key[0]}s | {key[1][2:]} | {d['games']}/{h['games'] if h else 0} | "
                 f"{d['gross']*100:+.2f} | {h['gross']*100:+.2f} | {d['gross_pos']*100:.0f}% | "
                 f"{d['net']*100:+.2f} | {h['net']*100:+.2f} |" if h else
                 f"| {key[0]}s | {key[1][2:]} | {d['games']}/0 | {d['gross']*100:+.2f} | — | "
                 f"{d['gross_pos']*100:.0f}% | {d['net']*100:+.2f} | — |")
    # verdict
    survivors = [k for k in disc if hold.get(k) and disc[k]["gross"] > 0 and hold[k]["gross"] > 0]
    tradeable = [k for k in survivors if disc[k]["net"] > 0 and hold[k]["net"] > 0]
    L += ["", f"**GROSS signal survives OOS in {len(survivors)} cells; NET (tradeable after "
          f"round-trip cost) in {len(tradeable)}.**",
          "_Gross-positive-but-net-negative = flow predicts direction but the move is too "
          "small to clear the round-trip cost (a real finding: signal exists, not harvestable "
          "this way — would need a maker/spread-capture execution, not a spread-crossing taker)._"]
    os.makedirs(os.path.dirname(FLOW_OUT), exist_ok=True)
    open(FLOW_OUT, "w").write("\n".join(L) + "\n")
    print(f"Wrote {FLOW_OUT}")
    print(f"  {len(games)} games · GROSS survives OOS: {len(survivors)} cells · tradeable NET: {len(tradeable)}")
    for k in sorted(survivors, key=lambda k: -hold[k]["gross"])[:8]:
        print(f"   {k[0]}s {k[1][2:]:10} gross disc {disc[k]['gross']*100:+.2f}¢ hold {hold[k]['gross']*100:+.2f}¢ "
              f"net hold {hold[k]['net']*100:+.2f}¢ ({disc[k]['games']}/{hold[k]['games']}g)")
    return survivors, tradeable


def main():
    if "--flow" in sys.argv:
        league = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else None
        flow_forward_scan(league)
        return
    league = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else None
    obs = observations(league)
    if not obs:
        print("no observations"); return
    obs.sort(key=lambda o: (o["date"], o["gid"]))
    gids = sorted({o["gid"] for o in obs})
    split_gids = set(gids[: int(len(gids) * 0.6)])
    disc = [o for o in obs if o["gid"] in split_gids]
    hold = [o for o in obs if o["gid"] not in split_gids]
    cut = sorted({o["date"] for o in hold})[0] if hold else "?"
    fresh = sum(1 for o in obs if o["stale"] <= FRESH_S)

    L = ["# EDGE SCAN — mining the corpus for real, OOS-validated edge",
         f"\n_`research/edge_discovery.py`. {len(obs):,} play observations across "
         f"**{len(gids)} games**{f' ({league})' if league else ''} "
         f"({fresh:,} with a fresh ≤{FRESH_S}s price bar). Time-split: discovery = "
         f"first 60% of games, holdout = games from {cut} on._\n",
         "> Charter read-order: disconfirmation first. The market is the prior; a model "
         "'edge' is guilty until it survives the holdout, clears fees, and has enough "
         "games behind it.\n"]

    L += calibration_block(obs, "ALL")[0]
    L += calibration_block(hold, "HOLDOUT only")[0]

    L.append("## Mispricing — discovery vs holdout\n")
    _, ds_rows = mispricing_scan(disc, "DISCOVERY (first 60% of games)")
    L += mispricing_scan(disc, "DISCOVERY (first 60% of games)")[0]
    _, hs_rows = mispricing_scan(hold, "HOLDOUT (later 40% of games)")
    L += mispricing_scan(hold, "HOLDOUT (later 40% of games)")[0]

    hmap = {(r["time"], r["gap"]): r for r in hs_rows}
    L += ["### Survivors — positive net edge in BOTH halves (the only cells worth a strategy)\n",
          "| time | gap | disc net ¢ | disc games | hold net ¢ | hold games |",
          "|---|---|---|---|---|---|"]
    survivors = []
    for r in ds_rows:
        if r["net_edge"] <= 0:
            continue
        h = hmap.get((r["time"], r["gap"]))
        if h and h["net_edge"] > 0:
            survivors.append((r, h))
            L.append(f"| {r['time']} | {r['gap']} | {r['net_edge']*100:+.1f} | "
                     f"{r['games']} | {h['net_edge']*100:+.1f} | {h['games']} |")
    if not survivors:
        L.append("| _(none cleared fees in both halves with enough games)_ ||||||")
    L.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(L) + "\n")
    print(f"Wrote {OUT}")
    print(f"  {len(obs):,} obs · {len(gids)} games · {len(survivors)} OOS-surviving cells")
    for r, h in survivors[:10]:
        print(f"   SURVIVOR {r['time']:16} {r['gap']:8} "
              f"disc {r['net_edge']*100:+.1f}¢/{r['games']}g  "
              f"hold {h['net_edge']*100:+.1f}¢/{h['games']}g")


if __name__ == "__main__":
    main()
