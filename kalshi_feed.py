#!/usr/bin/env python3
"""
kalshi_feed.py
───────────────
Real-time market data over Kalshi's WebSocket, normalized into a thread-safe
MarketState that strategies and the dashboard read.

Channels consumed (all the public per-market data Kalshi exposes):
  • ticker           → top of book, last price, sizes, volume, open interest
  • orderbook_delta  → full depth (snapshot + live deltas), both YES and NO books
  • trade            → every public trade (price, size, which side crossed)

The feed runs its own asyncio loop in a background thread, auto-reconnects, and
re-subscribes on reconnect.
"""
import asyncio, json, threading, time
from collections import deque
from datetime import datetime, timezone

import websockets

from kalshi_client import KalshiClient, PROD, d, fp


def _now_iso():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


class MarketState:
    """
    Live snapshot of one market. All reads/writes go through .lock.
    Prices are floats in DOLLARS (0.0–1.0); sizes are float contract counts.
    """
    def __init__(self, ticker):
        self.ticker = ticker
        self.lock = threading.Lock()

        # top of book (from `ticker` channel)
        self.yes_bid = None
        self.yes_ask = None
        self.yes_bid_size = None
        self.yes_ask_size = None
        self.last_price = None
        self.volume = None            # cumulative contracts
        self.open_interest = None
        self.dollar_volume = None

        # full depth (from `orderbook_delta`): price → resting size
        self.yes_book = {}            # bids to buy YES at price
        self.no_book = {}             # bids to buy NO at price (= offers on YES at 1-price)

        # tape (from `trade`)
        self.trades = deque(maxlen=200)   # dicts: price, count, taker_side, ts_ms

        # price history for timestamp-alignment: (ts_ms, mid)
        self.history = deque(maxlen=1200)

        self.last_update_ms = None
        self.connected = False
        self.msg_count = 0

    # ----- derived metrics (call under lock or accept slight staleness) -----
    @property
    def mid(self):
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2
        return self.last_price

    @property
    def spread(self):
        if self.yes_bid is not None and self.yes_ask is not None:
            return self.yes_ask - self.yes_bid
        return None

    def book_imbalance(self):
        """+1.0 = all bid-side (YES) depth, -1.0 = all ask-side (NO) depth."""
        yb = sum(self.yes_book.values())
        nb = sum(self.no_book.values())
        tot = yb + nb
        return (yb - nb) / tot if tot else 0.0

    def recent_trade_flow(self, secs=30):
        """Net signed contracts traded in last `secs` (YES-taker positive)."""
        if not self.trades:
            return 0.0
        cutoff = (self.last_update_ms or 0) - secs * 1000
        net = 0.0
        for t in self.trades:
            if t["ts_ms"] >= cutoff:
                net += t["count"] if t["taker_side"] == "yes" else -t["count"]
        return net

    def snapshot(self):
        """Cheap dict copy for the dashboard."""
        with self.lock:
            return {
                "ticker": self.ticker,
                "yes_bid": self.yes_bid, "yes_ask": self.yes_ask,
                "yes_bid_size": self.yes_bid_size, "yes_ask_size": self.yes_ask_size,
                "last_price": self.last_price, "volume": self.volume,
                "open_interest": self.open_interest, "mid": self.mid,
                "spread": self.spread, "imbalance": self.book_imbalance(),
                "trade_flow": self.recent_trade_flow(30),
                "trades": list(self.trades)[-15:],
                "history": list(self.history),
                "last_update_ms": self.last_update_ms,
                "connected": self.connected, "msg_count": self.msg_count,
            }


class KalshiFeed:
    """Owns the WS connection for one ticker and updates a MarketState."""

    def __init__(self, ticker, env=PROD, log=print):
        self.ticker = ticker
        self.client = KalshiClient(env)
        self.env = env
        self.state = MarketState(ticker)
        self.log = log
        self._thread = None
        self._stop = False

    def start(self):
        self._thread = threading.Thread(target=lambda: asyncio.run(self._run()),
                                        daemon=True)
        self._thread.start()
        return self.state

    def stop(self):
        self._stop = True

    async def _run(self):
        while not self._stop:
            try:
                await self._connect_once()
            except Exception as e:
                with self.state.lock:
                    self.state.connected = False
                self.log(f"WS disconnected: {type(e).__name__}: {str(e)[:120]} — retry 5s")
                await asyncio.sleep(5)

    async def _connect_once(self):
        headers = self.client.ws_headers()
        # websockets ≥10 uses additional_headers; older uses extra_headers
        try:
            conn = websockets.connect(self.env["ws"], additional_headers=headers,
                                      ping_interval=10, ping_timeout=10, open_timeout=10)
        except TypeError:
            conn = websockets.connect(self.env["ws"], extra_headers=headers,
                                      ping_interval=10, ping_timeout=10, open_timeout=10)
        async with conn as ws:
            with self.state.lock:
                self.state.connected = True
            self.log(f"WS connected → {self.ticker}")
            for cid, ch in enumerate(["ticker", "orderbook_delta", "trade"], start=1):
                await ws.send(json.dumps({
                    "id": cid, "cmd": "subscribe",
                    "params": {"channels": [ch], "market_tickers": [self.ticker]},
                }))
            async for raw in ws:
                if self._stop:
                    break
                self._handle(json.loads(raw))

    def _handle(self, m):
        typ = m.get("type")
        msg = m.get("msg", {})
        s = self.state
        with s.lock:
            s.msg_count += 1
            if typ == "ticker":
                s.yes_bid = d(msg.get("yes_bid_dollars"))
                s.yes_ask = d(msg.get("yes_ask_dollars"))
                s.yes_bid_size = fp(msg.get("yes_bid_size_fp"))
                s.yes_ask_size = fp(msg.get("yes_ask_size_fp"))
                s.last_price = d(msg.get("price_dollars"))
                s.volume = fp(msg.get("volume_fp"))
                s.open_interest = fp(msg.get("open_interest_fp"))
                s.dollar_volume = msg.get("dollar_volume")
                s.last_update_ms = msg.get("ts_ms")
                if s.mid is not None:
                    ts = msg.get("ts_ms") or int(time.time() * 1000)
                    s.history.append((ts, s.mid))
            elif typ == "orderbook_snapshot":
                s.yes_book, s.no_book = {}, {}
                for price, size in msg.get("yes_dollars_fp") or []:
                    s.yes_book[d(price)] = fp(size)
                for price, size in msg.get("no_dollars_fp") or []:
                    s.no_book[d(price)] = fp(size)
            elif typ == "orderbook_delta":
                book = s.yes_book if msg.get("side") == "yes" else s.no_book
                price = d(msg.get("price_dollars"))
                delta = fp(msg.get("delta_fp")) or 0
                book[price] = (book.get(price, 0) or 0) + delta
                if book[price] <= 0:
                    book.pop(price, None)
                s.last_update_ms = msg.get("ts_ms")
            elif typ == "trade":
                s.trades.append({
                    "price": d(msg.get("yes_price_dollars")),
                    "count": fp(msg.get("count_fp")) or 0,
                    "taker_side": msg.get("taker_side"),
                    "ts_ms": msg.get("ts_ms"),
                })
                s.last_update_ms = msg.get("ts_ms")
            elif typ == "error":
                self.log(f"WS server error: {msg}")
