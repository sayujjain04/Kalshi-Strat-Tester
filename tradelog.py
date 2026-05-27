#!/usr/bin/env python3
"""
tradelog.py — per-game data capture, organized for storing many games.

Each game gets its own folder under data/games/<game_id>/ holding:
  ticks.jsonl            event-based market+game snapshots (writes only on change,
                         stops post-game) — the replay record
  trades.jsonl           every public trade once (deduped) — the order-flow record
  plays.jsonl            ESPN play-by-play: exact score + win prob + text per play
  paper_decisions.jsonl  paper strategy opens/closes (raw market + signal + sim)
  real_decisions.jsonl   real strategy opens/closes
  real_orders.jsonl      real order attempts (requested vs actual fill → slippage)
  meta.json              game summary (teams, date, final, per-strategy P&L)

`game_id` is like "20260522_OKC_SAS" (date_away_home).
"""
import json, os
from collections import deque
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_ROOT, "data", "games")
RESULTS_DIR = os.path.join(_ROOT, "data", "results")


def game_dir(game_id):
    d = os.path.join(DATA_DIR, game_id)
    os.makedirs(d, exist_ok=True)
    return d


def append_result(rec):
    """Append one per-strategy outcome to the results ledger (the strategy
    performance history across all games + backtests)."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "strategy_history.jsonl"), "a") as f:
        f.write(json.dumps({"ts": _now(), **rec}) + "\n")


def _now():
    return datetime.now(timezone.utc).isoformat()


def append_line(gdir, name, rec):
    """Append one timestamped JSONL record to <gdir>/<name>."""
    with open(os.path.join(gdir, name), "a") as f:
        f.write(json.dumps({"ts": _now(), **rec}) + "\n")


def save_meta(gdir, meta):
    json.dump(meta, open(os.path.join(gdir, "meta.json"), "w"), indent=1)


def _normalize(t):
    """Flatten a paper Trade or a RealBroker trade-dict to common fields."""
    if isinstance(t, dict):                       # RealBroker
        return {"side": t.get("side"), "qty": t.get("count"),
                "entry_price": t.get("entry"), "exit_price": t.get("exit"),
                "entry_fee": t.get("fees"), "exit_fee": t.get("exit_fees"),
                "pnl": t.get("pnl"), "result": t.get("result"),
                "entry_reason": t.get("reason"), "exit_reason": t.get("reason_exit"),
                "req_entry": t.get("req_entry"), "req_exit": t.get("req_exit"),
                "req_count": t.get("req_count")}
    return {"side": t.side, "qty": t.qty,                       # paper Trade
            "entry_price": t.entry_price, "exit_price": t.exit_price,
            "entry_fee": getattr(t, "entry_fee", 0.0),
            "exit_fee": getattr(t, "exit_fee", 0.0),
            "pnl": t.pnl, "result": t.result,
            "entry_reason": t.entry_reason, "exit_reason": t.exit_reason,
            "entry_clock": t.entry_clock, "exit_clock": t.exit_clock}


class MarketRecorder:
    """Snapshots market+game state ON CHANGE (event-based), skips the repeated
    trade tape, and stops once the game is final. Writes <gdir>/ticks.jsonl."""
    def __init__(self, gdir, heartbeat_s=30):
        import time
        self.path = os.path.join(gdir, "ticks.jsonl")
        self.heartbeat_s = heartbeat_s
        self._time = time.time
        self._last = 0
        self._lastkey = None
        self._post_logged = False

    def flush(self, market, game):
        st = game.get("status")
        if st == "post":
            if self._post_logged:
                return
            self._post_logged = True
        sc = game.get("score") or {}
        key = (market.get("yes_bid"), market.get("yes_ask"), sc.get("home"),
               sc.get("away"), game.get("win_prob_home"), game.get("clock"), st)
        now = self._time()
        if key == self._lastkey and now - self._last < self.heartbeat_s:
            return
        self._lastkey, self._last = key, now
        m = {k: market.get(k) for k in
             ("yes_bid", "yes_ask", "yes_bid_size", "yes_ask_size", "last_price",
              "volume", "open_interest", "mid", "spread", "imbalance", "trade_flow")}
        g = {k: game.get(k) for k in
             ("period", "clock", "status", "score", "run_team", "run_size",
              "win_prob_home", "win_prob_ts")}
        with open(self.path, "a") as f:
            f.write(json.dumps({"ts": _now(), "market": m, "game": g}) + "\n")


class TradeTapeLogger:
    """Logs each public trade exactly once (deduped). Writes <gdir>/trades.jsonl."""
    def __init__(self, gdir):
        self.path = os.path.join(gdir, "trades.jsonl")
        self._seen = set()            # membership
        self._order = deque()         # insertion order, for true-FIFO eviction

    def flush(self, market):
        new = []
        for t in market.get("trades", []):
            k = (t.get("ts_ms"), t.get("price"), t.get("count"), t.get("taker_side"))
            if k in self._seen:
                continue
            self._seen.add(k)
            self._order.append(k)
            new.append(t)
        if not new:
            return
        with open(self.path, "a") as f:
            for t in new:
                f.write(json.dumps(t) + "\n")
        # Cap the dedup window, evicting the OLDEST keys. The old code sliced a `set`
        # (`list(set)[-2000:]`) — unordered, so it dropped ARBITRARY keys; once a game
        # passed 5000 trades the feed's rolling re-sends of still-recent trades looked
        # "new" and got re-appended (the C3 110k-line / 8 MB balloon). FIFO is safe
        # because Kalshi only re-sends recent trades, never long-evicted old ones.
        while len(self._order) > 5000:
            self._seen.discard(self._order.popleft())


class DecisionLogger:
    """Logs every strategy OPEN/CLOSE with raw_market (truth) + signal + sim
    (labeled assumptions — slippage is NOT presented as real). Writes
    <gdir>/<mode>_decisions.jsonl."""
    def __init__(self, gdir, mode):
        self.path = os.path.join(gdir, f"{mode}_decisions.jsonl")
        self.mode = mode
        self._open_id = {}
        self._closed_n = {}

    def flush(self, accounts, game, market, signal):
        for label, acc in accounts.items():
            ot = getattr(acc, "open_trade", None)
            oid = id(ot) if ot else None
            if ot is not None and oid != self._open_id.get(label):
                self._write("open", label, ot, game, market, signal, acc)
            self._open_id[label] = oid
            closed = getattr(acc, "closed", [])
            n = self._closed_n.get(label, 0)
            for t in closed[n:]:
                self._write("close", label, t, game, market, signal, acc)
            self._closed_n[label] = len(closed)

    def _write(self, event, label, t, game, market, signal, acc):
        f = _normalize(t)
        if event == "open":
            sim = {"sim_fill_price": f["entry_price"], "sim_fee": f["entry_fee"],
                   "qty": f["qty"], "reason": f["entry_reason"]}
        else:
            sim = {"sim_fill_price": f["exit_price"], "sim_fee": f["exit_fee"],
                   "sim_pnl": f["pnl"], "result": f["result"], "reason": f["exit_reason"]}
        rec = {
            "ts": _now(), "strategy": label, "event": event, "side": f["side"],
            "raw_market": {k: market.get(k) for k in
                           ("yes_bid", "yes_ask", "mid", "spread", "imbalance", "trade_flow")},
            "signal": signal,
            "game": {"period": game.get("period"), "clock": game.get("clock"),
                     "score": game.get("score"), "run_team": game.get("run_team"),
                     "run_size": game.get("run_size"), "win_prob_home": game.get("win_prob_home")},
            "sim": sim,
            "sim_slippage_assumed": getattr(acc, "slippage", None),
        }
        with open(self.path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
