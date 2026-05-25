#!/usr/bin/env python3
"""
shards.py — regenerate a static per-game order-flow page (docs/games/<id>.html)
from a captured game's COMMITTED logs, by replaying the real ticks through the
strategies (engine.simulate_captured, which includes the real order flow) and
rendering with the existing dashboard template.

Durable: covers every captured game in data/games/, independent of the ephemeral
live `dashboards/` dir. mtime-gated so finished games aren't needlessly re-rendered.

    python3 shards.py            # render only changed/live games
    python3 shards.py --all      # re-render every captured game
"""
import glob, json, os, sys

import engine, dashboard
import strategies as strat

ROOT = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(ROOT, "data", "games")
OUTDIR = os.path.join(ROOT, "docs", "games")


def _read_jsonl(path, limit=None):
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows[-limit:] if limit else rows


def _candles_from_ticks(ticks):
    """Reconstruct 1-min OHLC bars from tick mids (Kalshi keeps no tape history,
    but our ticks.jsonl recorded the mid on every change)."""
    buckets, order = {}, []
    for t in ticks:
        m = t.get("market") or {}
        mid = m.get("mid")
        ts = engine._iso_to_unix(t.get("ts"))
        if mid is None or ts is None:
            continue
        b = int(ts // 60 * 60)
        if b not in buckets:
            buckets[b] = {"o": mid, "h": mid, "l": mid, "c": mid, "v": 0.0,
                          "ts": b, "yb": m.get("yes_bid"), "ya": m.get("yes_ask")}
            order.append(b)
        c = buckets[b]
        c["h"] = max(c["h"], mid)
        c["l"] = min(c["l"], mid)
        c["c"] = mid
        c["yb"], c["ya"] = m.get("yes_bid"), m.get("yes_ask")
    return [buckets[b] for b in order]


def render_shard(game_dir, out_path):
    ticks_path = os.path.join(game_dir, "ticks.jsonl")
    if not os.path.exists(ticks_path):
        return False
    meta_file = {}
    mp = os.path.join(game_dir, "meta.json")
    if os.path.exists(mp):
        try:
            meta_file = json.load(open(mp))
        except Exception:
            meta_file = {}
    meta = engine.parse_ticker(meta_file.get("ticker", os.path.basename(game_dir)))
    if not meta:
        return False

    # replay the captured ticks (real order flow) through all strategies
    strategies = strat.build(list(strat.REGISTRY))
    pf = engine.simulate_captured(game_dir, strategies)
    if pf is None:
        return False

    ticks = _read_jsonl(ticks_path)
    last = ticks[-1] if ticks else {}
    market = dict(last.get("market") or {})
    market["trades"] = _read_jsonl(os.path.join(game_dir, "trades.jsonl"), limit=15)
    market["connected"] = False

    game = dict(last.get("game") or {})
    game["away"], game["home"] = meta["away"], meta["home"]
    game.setdefault("score", {"home": 0, "away": 0})
    if meta_file.get("final_score"):
        game["score"] = meta_file["final_score"]
    game["status"] = meta_file.get("final_status", "post")
    game["connected"] = False

    plays = [{"period": p.get("period"), "clock": p.get("clock"), "text": p.get("text")}
             for p in _read_jsonl(os.path.join(game_dir, "plays.jsonl"))]

    candles = _candles_from_ticks(ticks)
    model_series = []
    for t in ticks:
        wph = (t.get("game") or {}).get("win_prob_home")
        if wph is not None:
            model_series.append(wph if meta["yes_is_home"] else 1 - wph)

    vm = engine.build_vm(meta, market, game, candles, model_series, plays, pf,
                         "CAPTURED", 0)
    vm["back_href"] = "../index.html"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    dashboard.write(out_path, vm)
    return True


def _needs_render(game_dir, out_path):
    if not os.path.exists(out_path):
        return True
    om = os.path.getmtime(out_path)
    for f in ("ticks.jsonl", "paper_decisions.jsonl", "meta.json"):
        p = os.path.join(game_dir, f)
        if os.path.exists(p) and os.path.getmtime(p) > om:
            return True
    return False


def render_all(changed_only=True):
    os.makedirs(OUTDIR, exist_ok=True)
    done = []
    for d in sorted(glob.glob(os.path.join(GAMES, "*"))):
        if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "ticks.jsonl")):
            continue
        gid = os.path.basename(d)
        out = os.path.join(OUTDIR, f"{gid}.html")
        if changed_only and not _needs_render(d, out):
            continue
        try:
            if render_shard(d, out):
                done.append(gid)
        except Exception as e:
            print(f"shard {gid} error: {e}")
    return done


if __name__ == "__main__":
    full = "--all" in sys.argv
    print("rendered shards:", render_all(changed_only=not full))
