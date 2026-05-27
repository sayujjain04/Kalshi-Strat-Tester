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
import glob, json, os, sys, types
from datetime import datetime, timezone

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


def _results_from_log(game_dir, meta_file):
    """Build the leaderboard + journal from what ACTUALLY happened live
    (paper_decisions.jsonl + meta.json) — NOT a re-simulation, which diverges from the
    real tick-by-tick decisions. This is the truthful record that matches the board."""
    decs = _read_jsonl(os.path.join(game_dir, "paper_decisions.jsonl"))
    journal, cur, wins, losses = [], {}, {}, {}
    for d in decs:
        lab, ev, sim = d.get("strategy"), d.get("event"), (d.get("sim") or {})
        g = d.get("game") or {}
        clock = f"Q{g.get('period','')} {g.get('clock','')}".strip()
        tm = (d.get("ts") or "")[11:19]
        if ev == "open":
            t = types.SimpleNamespace(
                strategy=lab, side=d.get("side"), qty=sim.get("qty"),
                entry_price=sim.get("sim_fill_price"), entry_reason=sim.get("reason", ""),
                entry_clock=clock, entry_time=tm, exit_price=None, exit_reason=None,
                exit_clock=None, exit_time=None, pnl=None, result="OPEN")
            cur[lab] = t
            journal.append(t)
        elif ev == "close":
            t = cur.pop(lab, None)
            if t is None:
                t = types.SimpleNamespace(
                    strategy=lab, side=d.get("side"), qty=sim.get("qty"),
                    entry_price=None, entry_reason="", entry_clock=clock, entry_time=tm,
                    exit_price=None, exit_reason=None, exit_clock=None, exit_time=None,
                    pnl=None, result="")
                journal.append(t)
            t.exit_price = sim.get("sim_fill_price"); t.pnl = sim.get("sim_pnl")
            t.result = sim.get("result") or "CLOSED"; t.exit_reason = sim.get("reason", "")
            t.exit_clock = clock; t.exit_time = tm
            if t.result == "WIN":
                wins[lab] = wins.get(lab, 0) + 1
            elif t.result == "LOSS":
                losses[lab] = losses.get(lab, 0) + 1
    journal.sort(key=lambda t: (t.entry_time or t.exit_time or ""), reverse=True)

    lb = []
    for s in (meta_file.get("strategies") or []):
        lab, eq = s.get("strategy"), s.get("equity", 100.0) or 100.0
        w, l = wins.get(lab, 0), losses.get(lab, 0)
        lb.append({"strategy": lab, "equity": eq, "realized": eq - 100.0,
                   "unrealized": 0.0, "n_trades": s.get("trades", 0), "wins": w,
                   "losses": l, "win_rate": (w / (w + l) if (w + l) else None), "open": None})
    lb.sort(key=lambda x: x["equity"], reverse=True)
    return lb, journal


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

    ticks = _read_jsonl(ticks_path)
    # union-merge during git syncs can reorder JSONL lines, so sort by timestamp —
    # otherwise ticks[-1] (and the candle/model order) can grab a stale early tick.
    ticks.sort(key=lambda t: t.get("ts") or "")
    last = ticks[-1] if ticks else {}
    market = dict(last.get("market") or {})
    market["trades"] = _read_jsonl(os.path.join(game_dir, "trades.jsonl"), limit=15)
    market["connected"] = False

    game = dict(last.get("game") or {})
    game["away"], game["home"] = meta["away"], meta["home"]
    game.setdefault("score", {"home": 0, "away": 0})
    if meta_file.get("final_score"):
        game["score"] = meta_file["final_score"]
    # reflect the REAL state: final_status if the game ended (meta saved), else the
    # last captured tick's status (pre/in) so live games show LIVE with the live score.
    settled = meta_file.get("kalshi_result") in ("yes", "no")
    game["status"] = (meta_file.get("final_status")
                      or ("post" if settled else None)
                      or (last.get("game") or {}).get("status") or "post")
    game["connected"] = False
    live = game["status"] in ("in", "pre")

    plays = [{"period": p.get("period"), "clock": p.get("clock"), "text": p.get("text")}
             for p in _read_jsonl(os.path.join(game_dir, "plays.jsonl"))]

    candles = _candles_from_ticks(ticks)
    model_series = []
    for t in ticks:
        wph = (t.get("game") or {}).get("win_prob_home")
        if wph is not None:
            model_series.append(wph if meta["yes_is_home"] else 1 - wph)

    # leaderboard + journal from the ACTUAL live log (not a re-simulation, which
    # diverges from the real tick-by-tick decisions) so the shard matches the board.
    leaderboard, journal = _results_from_log(game_dir, meta_file)
    implied = market.get("mid") if market.get("mid") is not None else market.get("last_price")
    wph = game.get("win_prob_home")
    model = None if wph is None else (wph if meta["yes_is_home"] else 1 - wph)
    # live shards auto-refresh in the browser (~30s); finished games are static.
    vm = {
        "mode": "LIVE" if live else "CAPTURED", "refresh": 30 if live else 0,
        "yes_team": meta["yes_team"], "game": game, "market": market,
        "implied_p_yes": implied, "model_p_yes": model,
        "candles": candles, "model_series": model_series, "plays": plays,
        "leaderboard": leaderboard, "journal": journal,
        "generated": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "back_href": "../index.html",
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    dashboard.write(out_path, vm)
    return True


def _needs_render(game_dir, out_path):
    if not os.path.exists(out_path):
        return True
    # In-progress games change every tick — always re-render them. "In progress" =
    # meta.json missing OR present without a final_score (the ticker is written at
    # capture start, finals only at game end). Don't trust mtimes for live games: the
    # VM's git ops keep touching the shard file, which fooled the staleness check.
    mp = os.path.join(game_dir, "meta.json")
    if not os.path.exists(mp):
        return True
    try:
        if not json.load(open(mp)).get("final_score"):
            return True
    except Exception:
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
