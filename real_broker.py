#!/usr/bin/env python3
"""
real_broker.py — REAL order execution on Kalshi.   ⚠️  THIS SPENDS REAL MONEY.
────────────────────────────────────────────────────────────────────────────
Mirrors the paper Account's open()/close() surface so a strategy can't tell the
difference, but places actual marketable-limit orders and tracks real fills.
Completely separate from the paper tracker — nothing here touches the paper sim.

Hard safety caps (constructor):
  • capital      — never commit more than this in one position
  • stake_frac   — fraction of capital per trade
  • max_loss     — kill switch: halt once realized P&L hits −max_loss
  • max_orders   — kill switch: halt after this many orders placed
  • one position at a time, one ticker only, only manages orders it placed.
"""
import time, uuid
from datetime import datetime, timezone

from kalshi_client import KalshiClient, PROD, d, fp


def _cents(x):
    return int(round(x * 100))


class RealBroker:
    def __init__(self, ticker, capital=25.0, stake_frac=0.30, max_loss=10.0,
                 max_orders=40, fill_wait_s=4, log=print, client=None, game_dir=None):
        self.ticker = ticker
        self.game_dir = game_dir
        self.capital = capital
        self.starting_cash = capital
        self.stake_frac = stake_frac
        self.max_loss = abs(max_loss)
        self.max_orders = max_orders
        self.fill_wait_s = fill_wait_s
        self.client = client or KalshiClient(PROD)
        self.log = log
        self.strategy = "REAL"
        self.open_trade = None     # dict: side, count, entry, fees, reason, time
        self.closed = []
        self.realized = 0.0
        self.orders_placed = 0
        self.halted = False

    @property
    def flat(self):
        return self.open_trade is None

    def default_stake(self):
        return round(self.capital * self.stake_frac, 2)

    def _guard(self):
        if self.halted:
            return True
        if self.realized <= -self.max_loss:
            self.halted = True
            self.log(f"🛑 KILL SWITCH: realized ${self.realized:.2f} hit −${self.max_loss}")
        if self.orders_placed >= self.max_orders:
            self.halted = True
            self.log("🛑 KILL SWITCH: max orders reached")
        return self.halted

    # ----- raw order plumbing -----
    def _submit(self, action, side, count, price_cents):
        coid = str(uuid.uuid4())
        body = {"ticker": self.ticker, "action": action, "side": side,
                "count": int(count), "type": "limit", "client_order_id": coid}
        body["yes_price" if side == "yes" else "no_price"] = int(price_cents)
        r, err = self.client.post("/portfolio/orders", body)
        self.orders_placed += 1
        if err or not r:
            self.log(f"  order REJECTED: {err}")
            return None
        return r.get("order", r)

    def _log_order(self, action, side, req_price, req_count, fill_count, avg_fill, fees):
        """Record every order ATTEMPT (incl no-fills) for slippage/fee calibration."""
        import json
        if not self.game_dir:
            return
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "ticker": self.ticker,
               "action": action, "side": side, "req_price": req_price,
               "req_count": req_count, "fill_count": fill_count, "avg_fill": avg_fill,
               "fees": fees,
               "slippage": (None if avg_fill is None or req_price is None
                            else round(avg_fill - req_price, 4)),
               "fill_rate": (fill_count / req_count if req_count else 0)}
        with open(os.path.join(self.game_dir, "real_orders.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")

    def _cancel(self, oid):
        h = self.client.headers("DELETE", f"/trade-api/v2/portfolio/orders/{oid}")
        try:
            self.client.sess.delete(f"{PROD['rest']}/portfolio/orders/{oid}",
                                    headers=h, timeout=10)
        except Exception:
            pass

    def _await_fill(self, oid, side):
        """Poll real fills for this order. Returns (count, avg_price$, fees$)."""
        pf = "yes_price_dollars" if side == "yes" else "no_price_dollars"
        last = (0.0, 0.0, 0.0)
        for _ in range(self.fill_wait_s * 2):
            data, _ = self.client.get("/portfolio/fills", {"limit": 50}, auth=True)
            fills = [f for f in (data or {}).get("fills", []) if f.get("order_id") == oid]
            if fills:
                cnt = sum(fp(f.get("count_fp")) or 0 for f in fills)
                cost = sum((fp(f.get("count_fp")) or 0) * (d(f.get(pf)) or 0) for f in fills)
                fees = sum(d(f.get("fee_cost")) or (f.get("fee_cost") or 0) for f in fills)
                last = (cnt, (cost / cnt if cnt else 0), fees)
                # assume filled within a couple polls for marketable orders
                if cnt > 0:
                    return last
            time.sleep(0.5)
        self._cancel(oid)
        return last

    # ----- Account-compatible interface -----
    def open(self, side, market, reason="", clock="", stake=None):
        if not self.flat or self._guard():
            return None
        if side == "yes":
            price = market.get("yes_ask")
        else:
            yb = market.get("yes_bid")
            price = None if yb is None else 1 - yb       # NO ask = 1 − yes bid
        if price is None or price <= 0 or price >= 1:
            return None
        price_c = _cents(price)
        stake = stake if stake is not None else self.default_stake()
        count = int(stake // price)                       # contracts within stake
        if count < 1:
            return None
        self.log(f"[REAL] BUY {count} {side.upper()} @ {price_c}¢ (~${count*price:.2f}) — {reason}")
        order = self._submit("buy", side, count, price_c)
        if not order:
            self._log_order("buy", side, price, count, 0, None, 0)
            return None
        cnt, avg, fees = self._await_fill(order.get("order_id"), side)
        self._log_order("buy", side, price, count, cnt, avg, fees)
        if cnt <= 0:
            self.log("  no fill — order canceled")
            return None
        self.open_trade = {"side": side, "count": cnt, "entry": avg, "fees": fees,
                           "req_entry": price, "req_count": count,
                           "reason": reason, "time": datetime.now(timezone.utc).strftime("%H:%M:%S")}
        self.log(f"  ✅ FILLED {cnt:g} {side.upper()} @ ${avg:.3f} (fees ${fees:.3f})")
        return self.open_trade

    def close(self, market, reason="", clock=""):
        t = self.open_trade
        if not t:
            return None
        side = t["side"]
        if side == "yes":
            price = market.get("yes_bid")
        else:
            ya = market.get("yes_ask")
            price = None if ya is None else 1 - ya        # NO bid = 1 − yes ask
        if price is None:
            return None
        price_c = _cents(price)
        self.log(f"[REAL] SELL {t['count']:g} {side.upper()} @ {price_c}¢ — {reason}")
        order = self._submit("sell", side, t["count"], price_c)
        if not order:
            self._log_order("sell", side, price, t["count"], 0, None, 0)
            return None
        cnt, avg, fees = self._await_fill(order.get("order_id"), side)
        self._log_order("sell", side, price, t["count"], cnt, avg, fees)
        if cnt <= 0:
            self.log("  ⚠️ sell did not fill — STILL HOLDING, will retry next tick")
            return None
        pnl = cnt * (avg - t["entry"]) - fees - t["fees"]
        self.realized += pnl
        rec = {**t, "exit": avg, "exit_fees": fees, "req_exit": price, "pnl": pnl,
               "result": "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT"), "reason_exit": reason}
        self.closed.append(rec)
        self.open_trade = None
        self.log(f"  ✅ CLOSED @ ${avg:.3f} | P&L ${pnl:+.3f} ({rec['result']})  "
                 f"realized ${self.realized:+.2f}")
        return rec


def demo_round_trip(ticker, contracts=2):
    """Buy `contracts` YES at the ask, immediately sell at the bid. Shows real
    fills + the spread/fee cost. Tiny, bounded."""
    from kalshi_client import KalshiClient, PROD, d
    c = KalshiClient(PROD)
    m, _ = c.market(ticker)
    market = {"yes_bid": d(m.get("yes_bid_dollars")), "yes_ask": d(m.get("yes_ask_dollars"))}
    print(f"market: yes_bid={market['yes_bid']} yes_ask={market['yes_ask']}")
    b = RealBroker(ticker, capital=25.0, client=c)
    stake = contracts * (market["yes_ask"] or 0.5)
    b.open("yes", market, reason="demo round-trip", stake=stake)
    if not b.flat:
        time.sleep(1)
        m, _ = c.market(ticker)
        market = {"yes_bid": d(m.get("yes_bid_dollars")), "yes_ask": d(m.get("yes_ask_dollars"))}
        b.close(market, reason="demo close")
    print(f"\nNet realized: ${b.realized:+.3f} (this is the real spread+fee cost of a round trip)")
