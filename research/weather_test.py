#!/usr/bin/env python3
"""
weather_test.py — first cheap test of the WEATHER bet (EXP-011).

Thesis from the reading: Kalshi daily-high temperature markets OVERPRICE forecast
uncertainty (~1.27× realized) — the tail buckets are systematically too expensive. Test it
on settled markets, at a MORNING reference price (event-day 14:00Z, before the afternoon high
— no look-ahead), with the same rigor as sports (calibration + tradeable expectancy, net of
fees, event-clustered, OOS split). If real, this is the structural edge to build.

Each city-date event has ~6 bucket markets (Bxx.5 ranges + Txx tails); `result` says which
bucket won (= realized high). We reconstruct the morning implied distribution and ask:
  1. CALIBRATION — pooling all buckets, do low-implied-prob (tail) buckets win LESS than priced
     (overpriced) and the modal bucket win MORE (underpriced)?
  2. TRADEABLE — at the morning price, BUY the modal bucket / SELL (buy NO) the cheap tail
     buckets, hold to settlement, net of taker fee. Expectancy per bet, event-clustered, OOS.

    python3 research/weather_test.py
"""
import os, sys, time, statistics as st
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine                                            # noqa: E402
from kalshi_client import KalshiClient, PROD             # noqa: E402

OUT = os.path.join(ROOT, "docs", "WEATHER_TEST.md")
CITIES = ["KXHIGHNY"]   # first run: NYC only (most liquid). Expand once it works.
FEE_K = 0.07
REF_HOUR_UTC = 14            # ~9am ET / 8am CT — before the afternoon high (no look-ahead)
_MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}


def event_date(ev_ticker):
    """KXHIGHNY-26MAR24 → date(2026,3,24)."""
    import re
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})$", ev_ticker)
    if not m:
        return None
    yy, mon, dd = int(m.group(1)), _MONTHS.get(m.group(2)), int(m.group(3))
    return datetime(2000 + yy, mon, dd, REF_HOUR_UTC, tzinfo=timezone.utc)


def bucket_temp(m):
    fs, cs, stype = m.get("floor_strike"), m.get("cap_strike"), m.get("strike_type")
    if stype == "between" and fs is not None and cs is not None:
        return (fs + cs) / 2
    if stype == "less" and cs is not None:        # "X or below"
        return cs - 2
    if stype == "greater" and fs is not None:     # "X or above"
        return fs + 2
    return fs or cs


def _hurdle(p):
    return FEE_K * p * (1 - p)


def fetch_candles_retry(client, ticker, start, end, tries=4):
    """Candlestick fetch with 429 backoff — Kalshi rate-limits this endpoint hard."""
    series = ticker.split("-")[0]
    path = f"/series/{series}/markets/{ticker}/candlesticks"
    delay = 0.4
    for _ in range(tries):
        d, err = client.get(path, {"start_ts": int(start), "end_ts": int(end), "period_interval": 60})
        if err and "429" in err:
            time.sleep(delay); delay *= 2; continue
        if err or not d:
            return []
        out = []
        for cc in d.get("candlesticks", []):
            pr = (cc.get("price") or {})
            close = pr.get("close_dollars")
            if close is not None:
                out.append({"ts": cc.get("end_period_ts"), "c": float(close)})
        return out
    return []


def collect():
    c = KalshiClient(PROD)
    events = {}     # ev_ticker -> {date, buckets:[{temp, price, won}]}
    for series in CITIES:
        ms = c.markets(series_ticker=series, status="settled", limit=1000)
        byev = defaultdict(list)
        for m in ms:
            byev[m.get("event_ticker")].append(m)
        for ev, mk in byev.items():
            d = event_date(ev)
            if d is None:
                continue
            ref = int(d.timestamp())
            buckets = []
            for m in mk:
                res = m.get("result")
                if res not in ("yes", "no"):
                    continue
                tk = m["ticker"]
                ot = engine._iso_to_unix(m.get("open_time"))
                ct = engine._iso_to_unix(m.get("close_time"))
                if not ot or not ct:
                    continue
                cs = fetch_candles_retry(c, tk, int(ot), int(ct))
                # price at/just before the morning reference time (no look-ahead)
                px = None
                for cc in cs:
                    if cc.get("ts") and cc["ts"] <= ref and cc.get("c") is not None:
                        px = cc["c"]
                if px is None:
                    continue
                buckets.append({"temp": bucket_temp(m), "price": px,
                                "won": 1 if res == "yes" else 0, "ticker": tk})
                time.sleep(0.25)
            if len(buckets) >= 4:
                events[ev] = {"date": ev[-7:], "buckets": buckets}
    return events


def main():
    print("collecting weather markets + morning candles…", flush=True)
    events = collect()
    n_ev = len(events)
    if n_ev < 10:
        print(f"only {n_ev} events — insufficient"); return

    # 1. calibration: pool every bucket (morning implied prob vs won)
    allb = [b for e in events.values() for b in e["buckets"]]
    bands = [(0,.05),(.05,.1),(.1,.2),(.2,.4),(.4,.7),(.7,1.01)]
    cal = []
    for lo, hi in bands:
        sel = [b for b in allb if lo <= b["price"] < hi]
        if sel:
            cal.append((lo, hi, len(sel), st.mean(b["price"] for b in sel),
                        st.mean(b["won"] for b in sel)))

    # 2. tradeable: per event, BUY modal bucket; SELL (buy NO) cheap tail buckets (price<0.10)
    evs = sorted(events.items(), key=lambda kv: kv[1]["date"])
    split = set(k for k, _ in evs[: int(n_ev * 0.6)])

    def strat(subset):
        modal, tails = [], []   # per-event pnl lists
        for ev, e in subset:
            bs = e["buckets"]
            mb = max(bs, key=lambda b: b["price"])
            fill = min(1.0, mb["price"] + 0.01)            # cross to buy YES (approx ask)
            modal.append((mb["won"] - fill) - _hurdle(fill))
            for b in bs:
                if b["price"] < 0.10 and b is not mb:      # cheap tail → buy NO
                    nf = min(1.0, (1 - b["price"]) + 0.01)
                    tails.append(((1 - b["won"]) - nf) - _hurdle(nf))
        def prof(p):
            return None if not p else {"n": len(p), "exp": st.mean(p),
                                       "win": sum(1 for x in p if x > 0) / len(p)}
        return prof(modal), prof(tails)

    L = ["# WEATHER TEST — EXP-011: does Kalshi overprice temperature uncertainty?",
         f"\n_`research/weather_test.py`. {n_ev} city-date events across {len(CITIES)} cities, "
         f"morning reference price (event-day {REF_HOUR_UTC}:00Z, before the afternoon high — no "
         "look-ahead). Same rigor as sports: calibration + tradeable expectancy net of fees, "
         "event-clustered, 60/40 OOS split._\n",
         "## 1. Calibration — do tail buckets win less than priced? (overpricing signature)",
         "| morning implied band | n buckets | mean implied | realized win% | over/under |",
         "|---|---|---|---|---|"]
    for lo, hi, n, mp, rl in cal:
        tag = "OVERPRICED" if rl < mp - 0.01 else ("underpriced" if rl > mp + 0.01 else "fair")
        L.append(f"| {lo:.2f}–{hi:.2f} | {n} | {mp:.3f} | {rl:.3f} | {tag} |")

    md, td = strat([(k, events[k]) for k in events if k in split])
    mh, th = strat([(k, events[k]) for k in events if k not in split])
    L += ["", "## 2. Tradeable expectancy (hold to settlement, net of fee)",
          "| strategy | disc exp/bet | disc n | hold exp/bet | hold n | disc win% |",
          "|---|---|---|---|---|---|"]
    if md and mh:
        L.append(f"| BUY modal bucket | {md['exp']*100:+.2f}¢ | {md['n']} | {mh['exp']*100:+.2f}¢ | {mh['n']} | {md['win']*100:.0f}% |")
    if td and th:
        L.append(f"| SELL cheap tails (NO) | {td['exp']*100:+.2f}¢ | {td['n']} | {th['exp']*100:+.2f}¢ | {th['n']} | {td['win']*100:.0f}% |")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(L) + "\n")
    print(f"Wrote {OUT}")
    print(f"  {n_ev} events, {len(allb)} buckets")
    for lo, hi, n, mp, rl in cal:
        print(f"   band {lo:.2f}-{hi:.2f}: implied {mp:.3f} realized {rl:.3f} (n={n})")
    if md and mh:
        print(f"   BUY modal:  disc {md['exp']*100:+.2f}¢ ({md['n']}) / hold {mh['exp']*100:+.2f}¢ ({mh['n']})")
    if td and th:
        print(f"   SELL tails: disc {td['exp']*100:+.2f}¢ ({td['n']}) / hold {th['exp']*100:+.2f}¢ ({th['n']})")


if __name__ == "__main__":
    main()
