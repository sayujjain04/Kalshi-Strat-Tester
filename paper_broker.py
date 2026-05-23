#!/usr/bin/env python3
"""
paper_broker.py
────────────────
Paper-trading accounting. Each strategy gets its own independent $100 account so
we can compare which strategy actually makes money. No real orders are placed —
fills are simulated against the *real* live order book (you buy by crossing the
ask, sell by hitting the bid), which gives honest, internally-consistent P&L.

Everything is expressed in YES-price terms (dollars, 0.00–1.00):
  • A YES trade is long the YES contract: enter at yes_ask, exit at yes_bid.
  • A NO  trade is the opposite (short YES): enter at yes_bid, exit at yes_ask.
At settlement a YES contract pays $1 if YES wins; a NO trade pays $1 if YES loses.

Each round-trip is one Trade carrying a human-readable entry/exit reason and an
outcome, so the dashboard can explain exactly what a strategy did and why.

Swapping in real execution later (e.g. Kalshi demo) means implementing the same
open()/close() surface against an order-placement API — strategies don't change.
"""
import time
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now():
    return datetime.now(timezone.utc)


def kalshi_fee(qty, price):
    """Kalshi trading fee: ceil to next cent of 0.07 * contracts * P * (1-P).
    Verified against a real fill (2 @ $0.45 → $0.04). Zero at settlement (P=0/1).
    Symmetric in side, so the YES price works for NO trades too."""
    if price is None or qty <= 0:
        return 0.0
    return math.ceil(0.07 * qty * price * (1.0 - price) * 100) / 100.0


# how far off the touch we assume fills land (you don't always get the quoted
# price): buys pay this much more, sells receive this much less. The real demo
# got the exact touch on small size pre-game, but live/fast markets slip — 0.5¢
# is a realistic-conservative middle.
DEFAULT_SLIPPAGE = 0.005


@dataclass
class Trade:
    strategy: str
    side: str                 # "yes" | "no"
    qty: float                # contracts
    entry_price: float        # executed YES price at entry (dollars)
    entry_time: str
    entry_clock: str          # game clock at entry, for readability
    entry_reason: str
    stake: float              # dollars committed
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_clock: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None      # dollars, NET of fees
    result: str = "OPEN"             # OPEN | WIN | LOSS | FLAT
    entry_fee: float = 0.0
    exit_fee: float = 0.0

    def cost_per_contract(self):
        # what you pay per contract to hold this side
        return self.entry_price if self.side == "yes" else (1.0 - self.entry_price)

    def pnl_per_contract(self, exit_yes_price):
        if self.side == "yes":
            return exit_yes_price - self.entry_price
        return self.entry_price - exit_yes_price

    def unrealized(self, market):
        """Mark to the price we could exit at right now."""
        if self.result != "OPEN":
            return 0.0
        if self.side == "yes":
            mark = market.get("yes_bid")          # we'd sell into the bid
        else:
            mark = market.get("yes_ask")          # we'd buy back at the ask
        if mark is None:
            mark = market.get("mid") or market.get("last_price") or self.entry_price
        # subtract the fee already paid on entry (exit fee unknown until we close)
        return self.qty * self.pnl_per_contract(mark) - self.entry_fee


class Account:
    """One strategy's independent paper money."""

    def __init__(self, strategy_name, starting_cash=100.0, stake_frac=0.20,
                 log=print, slippage=DEFAULT_SLIPPAGE):
        self.strategy = strategy_name
        self.starting_cash = starting_cash
        self.stake_frac = stake_frac          # fraction of bankroll risked per trade
        self.slippage = slippage
        self.realized = 0.0
        self.open_trade: Optional[Trade] = None
        self.closed: list[Trade] = []
        self.log = log

    # ----- queries -----
    @property
    def flat(self):
        return self.open_trade is None

    def default_stake(self):
        return round(self.starting_cash * self.stake_frac, 2)

    def equity(self, market):
        unreal = self.open_trade.unrealized(market) if self.open_trade else 0.0
        return self.starting_cash + self.realized + unreal

    def stats(self, market):
        wins = sum(1 for t in self.closed if t.result == "WIN")
        losses = sum(1 for t in self.closed if t.result == "LOSS")
        return {
            "strategy": self.strategy,
            "equity": self.equity(market),
            "realized": self.realized,
            "unrealized": self.open_trade.unrealized(market) if self.open_trade else 0.0,
            "n_trades": len(self.closed),
            "wins": wins, "losses": losses,
            "win_rate": (wins / (wins + losses)) if (wins + losses) else None,
            "open": self.open_trade,
        }

    # ----- actions -----
    def open(self, side, market, reason, clock="", stake=None):
        """Open a position. side='yes' buys YES at ask; 'no' shorts YES at bid."""
        if self.open_trade is not None:
            return None
        s = self.slippage
        if side == "yes":                                  # buy YES at ask, pay up
            base = market.get("yes_ask") or market.get("mid") or market.get("last_price")
            price = None if base is None else min(0.99, base + s)
        else:                                              # short YES at bid, receive less
            base = market.get("yes_bid") or market.get("mid") or market.get("last_price")
            price = None if base is None else max(0.01, base - s)
        if price is None or price <= 0 or price >= 1:
            return None
        stake = stake if stake is not None else self.default_stake()
        cost = price if side == "yes" else (1.0 - price)
        if cost <= 0:
            return None
        qty = round(stake / cost, 2)
        if qty <= 0:
            return None
        fee = kalshi_fee(qty, price)
        t = Trade(strategy=self.strategy, side=side, qty=qty, entry_price=price,
                  entry_time=_now().strftime("%H:%M:%S"), entry_clock=clock,
                  entry_reason=reason, stake=stake, entry_fee=fee)
        self.open_trade = t
        self.log(f"[{self.strategy}] OPEN {side.upper()} {qty:g}@¢{price*100:.0f} "
                 f"(${stake:.0f}) — {reason}")
        return t

    def close(self, market, reason, clock="", settle_yes=None):
        """Close the open position. settle_yes=True/False forces a $1/$0 settlement."""
        t = self.open_trade
        if t is None:
            return None
        s = self.slippage
        if settle_yes is not None:                         # settles free at $1/$0
            exit_price = 1.0 if settle_yes else 0.0
            exit_fee = 0.0
        else:
            if t.side == "yes":                            # sell YES into the bid
                base = market.get("yes_bid")
                exit_price = None if base is None else max(0.01, base - s)
            else:                                          # cover short: buy YES at ask
                base = market.get("yes_ask")
                exit_price = None if base is None else min(0.99, base + s)
            if exit_price is None:
                exit_price = market.get("mid") or market.get("last_price") or t.entry_price
            exit_fee = kalshi_fee(t.qty, exit_price)
        pnl = t.qty * t.pnl_per_contract(exit_price) - t.entry_fee - exit_fee
        t.exit_price = exit_price
        t.exit_fee = exit_fee
        t.exit_time = _now().strftime("%H:%M:%S")
        t.exit_clock = clock
        t.exit_reason = reason
        t.pnl = pnl
        t.result = "WIN" if pnl > 1e-9 else ("LOSS" if pnl < -1e-9 else "FLAT")
        self.realized += pnl
        self.closed.append(t)
        self.open_trade = None
        self.log(f"[{self.strategy}] CLOSE {t.side.upper()} @¢{exit_price*100:.0f} "
                 f"P&L={'+' if pnl>=0 else ''}${pnl:.2f} {t.result} — {reason}")
        return t


class Portfolio:
    """Holds every strategy's account and exposes a unified trade journal."""

    def __init__(self, starting_cash=100.0, log=print, slippage=DEFAULT_SLIPPAGE):
        self.starting_cash = starting_cash
        self.accounts: dict[str, Account] = {}
        self.log = log
        self.slippage = slippage

    def account_for(self, strategy_name, stake_frac=0.20):
        if strategy_name not in self.accounts:
            self.accounts[strategy_name] = Account(
                strategy_name, self.starting_cash, stake_frac, self.log,
                slippage=self.slippage)
        return self.accounts[strategy_name]

    def journal(self):
        """All trades (open + closed) across strategies, newest first."""
        rows = []
        for acc in self.accounts.values():
            rows.extend(acc.closed)
            if acc.open_trade:
                rows.append(acc.open_trade)
        rows.sort(key=lambda t: t.entry_time, reverse=True)
        return rows

    def leaderboard(self, market):
        return sorted((acc.stats(market) for acc in self.accounts.values()),
                      key=lambda s: s["equity"], reverse=True)
