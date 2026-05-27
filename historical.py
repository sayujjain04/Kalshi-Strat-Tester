#!/usr/bin/env python3
"""
historical.py — build & maintain a DURABLE, committed backtest corpus.

Replaces backtest.py's ephemeral /tmp, 35-day, NBA-only discovery. Pulls every
settled game market across leagues that still has retrievable Kalshi candles +
ESPN play-by-play/win-prob, and stores a compact gzipped record per game under
data/backtest/<game_id>.json.gz — committed, reproducible, resumable.

Kalshi retains ~2 months of 1-min candles, so this is incremental: re-run it
periodically and it fetches only newly-settled games. Heavy batch — run with real
compute (local/CI), NOT the e2-micro; commit the corpus.

    python3 historical.py                      # incremental backfill, all leagues
    python3 historical.py --leagues KXNBAGAME   # one league
    python3 historical.py --limit 3             # fetch at most N new games (testing)
    python3 historical.py --stats               # report corpus coverage only
"""
import glob, gzip, json, os, sys, time
from collections import Counter
from datetime import datetime, timezone, timedelta

import requests

from kalshi_client import KalshiClient, PROD
from espn_feed import LEAGUES, sport_for, espn_abbr
import engine

ROOT = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(ROOT, "data", "backtest")
UA = {"User-Agent": "r/2.0"}
ESPN = "http://site.api.espn.com/apis/site/v2/sports"


def _settled_index(client, series):
    """{(date, frozenset({espn away, espn home})): ticker} for settled+finalized markets."""
    idx, results = {}, {}
    for status in ("settled", "finalized"):
        for m in client.markets(series_ticker=series, status=status, limit=200):
            p = engine.parse_ticker(m.get("ticker", ""))
            if p:
                key = (p["date"], frozenset({espn_abbr(p["away"]), espn_abbr(p["home"])}))
                idx[key] = m["ticker"]
                results[m["ticker"]] = m.get("result") if m.get("result") in ("yes", "no") else None
    return idx, results


def discover(series, sess, client):
    """Match Kalshi settled game markets to ESPN finished events (per-day scoreboard
    over the markets' date span). Returns [{espn_id,date,away,home,ticker,league}]."""
    idx, results = _settled_index(client, series)
    if not idx:
        return []
    sport = sport_for(series)
    days = sorted({d for d, _ in idx})
    d = datetime.strptime(days[0], "%Y%m%d").replace(tzinfo=timezone.utc)
    hi = datetime.strptime(days[-1], "%Y%m%d").replace(tzinfo=timezone.utc)
    out = []
    while d <= hi:
        ds = d.strftime("%Y%m%d")
        try:
            r = sess.get(f"{ESPN}/{sport}/scoreboard", params={"dates": ds},
                         headers=UA, timeout=15).json()
        except Exception:
            d += timedelta(days=1); continue
        for ev in r.get("events", []):
            c = ev["competitions"][0]
            if c["status"]["type"]["state"] != "post":
                continue
            cs = {x["homeAway"]: x for x in c["competitors"]}
            away, home = cs["away"]["team"]["abbreviation"], cs["home"]["team"]["abbreviation"]
            key = (ds, frozenset({away, home}))
            if key in idx:
                out.append({"espn_id": ev["id"], "date": ds, "away": away, "home": home,
                            "ticker": idx[key], "league": LEAGUES[series][0],
                            "kalshi_result": results.get(idx[key])})
        d += timedelta(days=1)
        time.sleep(0.12)
    return out


def _path(ticker):
    return os.path.join(CORPUS, f"{engine.game_id(engine.parse_ticker(ticker))}.json.gz")


def fetch_and_store(g, client):
    out = _path(g["ticker"])
    if os.path.exists(out):
        return "skip"
    try:
        data = engine.fetch_replay_data(g["espn_id"], g["ticker"], client=client)
    except Exception as e:
        return f"err:{type(e).__name__}"
    if not data or len(data.get("candles") or []) <= 5:
        return "nocandles"
    data["kalshi_result"] = g.get("kalshi_result")   # official settlement for simulate()
    try:                                              # condensed trade tape for order-flow backtests
        data["flow"] = fetch_flow(client, g["ticker"])
    except Exception:
        data["flow"] = []
    os.makedirs(CORPUS, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump({"g": g, "data": data}, f)
    return "ok"


def build(series_list=None, limit=None):
    series_list = series_list or list(LEAGUES)
    sess = requests.Session(); sess.headers.update(UA)
    client = KalshiClient(PROD)
    tally, fetched = Counter(), 0
    for series in series_list:
        games = discover(series, sess, client)
        print(f"{series}: {len(games)} matched settled games", flush=True)
        for g in games:
            if limit is not None and fetched >= limit:
                break
            r = fetch_and_store(g, client)
            tally[r] += 1
            if r == "ok":
                fetched += 1
                time.sleep(0.25)            # polite to ESPN/Kalshi
            if (tally["ok"] + tally["skip"]) % 25 == 0 and tally["ok"]:
                print(f"  …{dict(tally)}", flush=True)
        print(f"  {series} done: {dict(tally)}", flush=True)
        if limit is not None and fetched >= limit:
            break
    return dict(tally)


def fetch_flow(client, ticker, bucket_s=30, max_pages=80):
    """Pull the full historical trade tape (/markets/trades, paginated) and condense to
    per-30s buckets: [bucket_ts, net_signed_flow, volume, last_yes_price]. Net flow uses
    the order-flow convention (YES-taker +, NO-taker −). Compact (~hundreds/game) so it
    fits git; raw per-trade would be millions of rows → that's the Postgres trigger."""
    buckets, cursor = {}, None
    for _ in range(max_pages):
        p = {"ticker": ticker, "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        d, err = client.get("/markets/trades", p)
        if err or not d:
            break
        trades = d.get("trades") or []
        for tr in trades:
            ts = engine._iso_to_unix(tr.get("created_time"))
            if ts is None:
                continue
            cnt = float(tr.get("count_fp") or 0)
            signed = cnt if tr.get("taker_side") == "yes" else -cnt
            price = tr.get("yes_price_dollars")
            b = int(ts // bucket_s * bucket_s)
            e = buckets.setdefault(b, [0.0, 0.0, None])
            e[0] += signed
            e[1] += cnt
            if price not in (None, ""):
                e[2] = float(price)
        cursor = d.get("cursor")
        if not cursor or not trades:
            break
        time.sleep(0.1)
    return [[b, round(v[0], 2), round(v[1], 2), v[2]] for b, v in sorted(buckets.items())]


def backfill_flow(limit=None):
    """Add condensed trade-flow to each committed corpus game that lacks it. Lets the
    order-flow strategies (trade_flow-based) finally backtest on ALL history, not just
    the handful of captured-live games."""
    client = KalshiClient(PROD)
    done, tally = [], Counter()
    for p in sorted(glob.glob(os.path.join(CORPUS, "*.json.gz")))[:limit]:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            tally["readerr"] += 1; continue
        if "flow" in rec.get("data", {}):   # presence, not truthiness — empty [] = probed, no tape
            tally["skip"] += 1; continue
        ticker = (rec.get("g") or {}).get("ticker")
        if not ticker:
            tally["noticker"] += 1; continue
        try:
            flow = fetch_flow(client, ticker)
        except Exception as e:
            print(f"  flow err {os.path.basename(p)}: {e}", flush=True); tally["err"] += 1; continue
        rec["data"]["flow"] = flow
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump(rec, f)
        tally["ok"] += 1
        done.append(os.path.basename(p))
        if tally["ok"] % 20 == 0:
            print(f"  …flow backfilled {tally['ok']} games", flush=True)
    print(f"flow backfill: {dict(tally)}", flush=True)
    return done


def load_corpus(limit=None):
    """[(g, data)] for backtest.run_suite / engine.simulate."""
    out = []
    for p in sorted(glob.glob(os.path.join(CORPUS, "*.json.gz")))[:limit]:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                rec = json.load(f)
            if rec.get("data", {}).get("candles"):
                out.append((rec["g"], rec["data"]))
        except Exception:
            pass
    return out


def stats():
    c = Counter()
    for p in glob.glob(os.path.join(CORPUS, "*.json.gz")):
        parts = os.path.basename(p).replace(".json.gz", "").split("_")
        c[parts[1] if len(parts) > 2 else "NBA"] += 1
    print(f"corpus @ {CORPUS}: {dict(c)} · total {sum(c.values())} games")
    return c


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--stats" in a:
        stats()
    elif "--flow" in a:
        limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
        print("== trade-flow backfill ==", flush=True)
        done = backfill_flow(limit)
        print(f"flow added to {len(done)} games", flush=True)
    else:
        series = a[a.index("--leagues") + 1].split(",") if "--leagues" in a else None
        limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
        print("== backfill ==", flush=True)
        print("done:", build(series, limit))
        stats()
