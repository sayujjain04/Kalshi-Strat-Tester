#!/usr/bin/env python3
"""
strategies.py
──────────────
Pluggable strategies. Each implements evaluate(ctx), called every loop tick.
It reads ctx and acts on its own paper Account (ctx.broker) via .open / .close.
One open position at a time per strategy.

DESIGN PRINCIPLE (from the strategy handoff): ESPN game data (score, runs,
win_prob) is ~5–15s stale and updates per-play; Kalshi price/book/trades are
sub-second. The price LEADS, the model LAGS. So: use slow ESPN data for context
and entry framing, use fast Kalshi data for danger detection and exits. Never let
a lagged number hold a position open while the live price moves against you.

Engine provides on ctx (built once, not re-coded per strategy):
  • aligned_implied — Kalshi mid AS OF the model's timestamp (lag-safe compare)
  • model_age_s     — how stale the model is (live); ~0 in replay
  • game_fresh      — True only when ESPN actually advanced (dead-data guard)
  • status / seconds_left / final_period / near_settlement — settlement-cliff guards

`needs` documents required data. "orderflow" ⇒ live-only (Kalshi has no historical
depth/tape, so those strategies idle in replay).
"""
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class Context:
    market: dict
    game: dict
    yes_team: str
    yes_is_home: bool
    implied_p_yes: Optional[float]    # LIVE market mid
    model_p_yes: Optional[float]      # ESPN model probability for YES side
    aligned_implied: Optional[float]  # market mid as of the model's timestamp
    model_ts: Optional[int]
    now_ts: Optional[int]
    model_age_s: Optional[float]
    clock: str
    broker: "Account"
    status: str = "in"
    seconds_left: Optional[float] = None
    final_period: bool = False
    near_settlement: bool = False
    game_fresh: bool = True
    is_replay: bool = False


# ── shared helpers ────────────────────────────────────────────────────────────
def _other(ctx):
    return ctx.game["away"] if ctx.yes_is_home else ctx.game["home"]


def _yes_side_score(ctx):
    s = ctx.game["score"]
    return (s["home"], s["away"]) if ctx.yes_is_home else (s["away"], s["home"])


def _model_yes_at(game, yes_is_home, idx):
    hist = game.get("wp_history") or []
    if not hist:
        return None
    wp = hist[idx][1]
    return wp if yes_is_home else 1 - wp


def _model_velocity(game, yes_is_home, now_ts, window_s=60):
    """Change in model P(yes) over the last `window_s` seconds (+ = rising)."""
    hist = game.get("wp_history") or []
    if len(hist) < 2 or now_ts is None:
        return 0.0
    def y(wp):
        return wp if yes_is_home else 1 - wp
    cur = y(hist[-1][1])
    past = y(hist[0][1])
    for ts, wp in hist:
        if ts is not None and ts <= now_ts - window_s * 1000:
            past = y(wp)
    return cur - past


def _price_back(market, ref_ts, secs):
    """Mid price `secs` before ref_ts, from (ts_ms, mid) history."""
    hist = market.get("history") or []
    if not hist or ref_ts is None:
        return None
    target = ref_ts - secs * 1000
    out = None
    for t, mid in hist:
        if t is not None and t <= target:
            out = mid
        else:
            break
    return out


def _flow_confirms(ctx, side):
    """Live order flow / book imbalance points the same way as the trade."""
    flow = ctx.market.get("trade_flow") or 0
    imb = ctx.market.get("imbalance") or 0
    if side == "yes":
        return flow > 0 or imb > 0
    return flow < 0 or imb < 0


class _Persist:
    """A directional signal must hold across ≥min_updates ESPN ticks and ≥min_secs."""
    def __init__(self, min_updates=2, min_secs=30):
        self.min_updates, self.min_secs = min_updates, min_secs
        self.reset()

    def reset(self):
        self.dir = 0
        self.since_ts = None
        self.count = 0
        self.last_model_ts = None

    def update(self, qualifies, direction, model_ts, now_ts):
        if not qualifies or direction != self.dir:
            if qualifies:
                self.dir, self.since_ts, self.count, self.last_model_ts = \
                    direction, now_ts, 1, model_ts
            else:
                self.reset()
            return False
        if model_ts is not None and model_ts != self.last_model_ts:
            self.count += 1
            self.last_model_ts = model_ts
        elapsed = ((now_ts - self.since_ts) / 1000.0) if (now_ts and self.since_ts) else 0
        return self.count >= self.min_updates and elapsed >= self.min_secs


# ── base ──────────────────────────────────────────────────────────────────────
class Strategy:
    key = "base"
    label = "Base"
    description = ""
    needs = set()
    stake_frac = 0.20

    def __init__(self, params=None):
        self.params = params or {}
        self._entry_ts = None

    def p(self, name, default):
        return self.params.get(name, default)

    def evaluate(self, ctx):
        raise NotImplementedError

    # --- shared guards ---
    def _live(self, ctx):
        """Only act on an in-progress game."""
        return ctx.status == "in"

    def _timeup(self, ctx, cap_s):
        return (self._entry_ts and ctx.now_ts
                and (ctx.now_ts - self._entry_ts) / 1000.0 >= cap_s)

    def _force_flat(self, ctx, threshold_s, reason="Forced flat before settlement cliff"):
        """Close any open position approaching the end of the final period/OT."""
        b = ctx.broker
        if (b.open_trade and ctx.final_period and ctx.seconds_left is not None
                and ctx.seconds_left <= threshold_s):
            b.close(ctx.market, clock=ctx.clock, reason=reason)
            self._entry_ts = None
            return True
        return False

    def _hard_stop(self, ctx, stop):
        """Close if the live price has moved `stop` against the open position."""
        t = ctx.broker.open_trade
        if not t:
            return False
        yb, ya = ctx.market.get("yes_bid"), ctx.market.get("yes_ask")
        adverse = (t.side == "yes" and yb is not None and t.entry_price - yb >= stop) or \
                  (t.side == "no" and ya is not None and ya - t.entry_price >= stop)
        if adverse:
            ctx.broker.close(ctx.market, clock=ctx.clock,
                             reason=f"Hard stop {stop*100:.0f}¢ — price moving against us")
            self._entry_ts = None
            return True
        return False


# ── 1. Edge, naive (CONTROL — exposes the latency trap when run live) ──────────
class EdgeNaive(Strategy):
    key = "edge_naive"
    label = "Edge (naive control)"
    description = ("Compares ESPN model to the LIVE price with no lag handling. "
                   "A baseline to show how much the lag fix matters — NOT meant to "
                   "be trusted live (its replay numbers are a latency-free artifact).")
    needs = {"price", "winprob"}
    stake_frac = 0.10                 # control / benchmark only (Kelly artifact)

    def evaluate(self, ctx):
        b = ctx.broker
        if not b.flat:
            if self._force_flat(ctx, 60):
                return
            mp, ip = ctx.model_p_yes, ctx.implied_p_yes
            t = b.open_trade
            if mp is not None and ip is not None and (
                    (t.side == "yes" and mp - ip <= self.p("exit_edge", 0.02)) or
                    (t.side == "no" and mp - ip >= -self.p("exit_edge", 0.02))):
                b.close(ctx.market, clock=ctx.clock, reason=f"Edge closed ({ip:.0%})")
            return
        mp, ip = ctx.model_p_yes, ctx.implied_p_yes
        if not self._live(ctx) or ctx.near_settlement or mp is None or ip is None:
            return
        if ip < 0.04 or ip > 0.96:
            return
        enter, edge = self.p("enter_edge", 0.06), mp - ctx.implied_p_yes
        if edge >= enter:
            b.open("yes", ctx.market, clock=ctx.clock,
                   reason=f"[naive] model {mp:.0%} vs market {ip:.0%} — YES cheap {edge*100:.0f}¢")
        elif edge <= -enter:
            b.open("no", ctx.market, clock=ctx.clock,
                   reason=f"[naive] model {mp:.0%} vs market {ip:.0%} — YES rich {-edge*100:.0f}¢")


# ── 2. Mean-Reversion to Model — lag-safe (aligned + persistence) ─────────────
class ModelRevert(Strategy):
    key = "model_revert"
    label = "Mean-Reversion to Model"
    description = ("Treats ESPN model as fair value. Enters toward the time-aligned "
                   "price only on a BIG gap (≥15¢) held ≥30s — fee-aware, since a "
                   "small edge loses to fees+slippage. Marginal/fragile net of costs.")
    needs = {"price", "winprob"}
    stake_frac = 0.10                 # Kelly ≈0.08 (tiny edge) → small

    def __init__(self, params=None):
        super().__init__(params)
        self._pers = _Persist(2, self.p("persist_s", 30))

    def evaluate(self, ctx):
        b = ctx.broker
        mp, ap, ip = ctx.model_p_yes, ctx.aligned_implied, ctx.implied_p_yes
        if not b.flat:
            if self._force_flat(ctx, 60) or self._hard_stop(ctx, self.p("hard_stop", 0.05)):
                return
            if mp is not None and ip is not None and abs(mp - ip) <= self.p("exit_edge", 0.03):
                b.close(ctx.market, clock=ctx.clock, reason=f"Converged (model {mp:.0%} ≈ market {ip:.0%})")
            elif self._timeup(ctx, self.p("time_cap_s", 240)):
                b.close(ctx.market, clock=ctx.clock, reason="Time cap reached")
            return
        if not self._live(ctx) or ctx.near_settlement or mp is None or ap is None:
            return
        if ip is not None and (ip < 0.04 or ip > 0.96):
            return
        enter = self.p("enter_edge", 0.15)        # fee-aware: small edges lose to costs
        edge = mp - ap
        direction = 1 if edge >= enter else (-1 if edge <= -enter else 0)
        if self._pers.update(direction != 0, direction, ctx.model_ts, ctx.now_ts) and direction:
            side = "yes" if direction > 0 else "no"
            b.open(side, ctx.market, clock=ctx.clock,
                   reason=f"Model {mp:.0%} vs aligned price {ap:.0%} — {edge*100:+.0f}¢ gap held {self.p('persist_s',30)}s+")
            self._entry_ts = ctx.now_ts
            self._pers.reset()


# ── 3. Win-Prob Momentum (model rising; needs order-flow gate ⇒ live-only) ────
class WPMomentum(Strategy):
    key = "wp_momentum"
    label = "Win-Prob Momentum"
    description = ("Buys a team while ESPN's model swings ≥8pts/60s its way and the "
                   "aligned price lags ≥5¢ — ONLY if live order flow agrees. The "
                   "empirical foil to Run Momentum. Live-only (flow gate required).")
    needs = {"price", "winprob", "orderflow"}
    stake_frac = 0.10                 # live-only, untested on history → conservative

    def __init__(self, params=None):
        super().__init__(params)
        self._side = None

    def evaluate(self, ctx):
        b = ctx.broker
        mp, ap, ip = ctx.model_p_yes, ctx.aligned_implied, ctx.implied_p_yes
        if not b.flat:
            if self._force_flat(ctx, 60) or self._hard_stop(ctx, self.p("hard_stop", 0.05)):
                self._side = None
                return
            if mp is not None and ip is not None and abs(mp - ip) <= self.p("exit_edge", 0.02):
                b.close(ctx.market, clock=ctx.clock, reason=f"Price caught up to model ({ip:.0%})"); self._side = None
                return
            # momentum died: model stalled/reversed against us recently
            vel = _model_velocity(ctx.game, ctx.yes_is_home, ctx.now_ts, 12)
            if (self._side == "yes" and vel <= 0) or (self._side == "no" and vel >= 0):
                b.close(ctx.market, clock=ctx.clock, reason="Momentum died (model stalled)"); self._side = None
                return
            if self._timeup(ctx, self.p("time_cap_s", 180)):
                b.close(ctx.market, clock=ctx.clock, reason="Time cap reached"); self._side = None
            return
        if not self._live(ctx) or ctx.near_settlement or not ctx.game_fresh or mp is None or ap is None:
            return
        win = self.p("window_s", 60)
        vel = _model_velocity(ctx.game, ctx.yes_is_home, ctx.now_ts, win)
        vmin, gap = self.p("vel_min", 0.08), self.p("gap_min", 0.05)
        if vel >= vmin and (mp - ap) >= gap and _flow_confirms(ctx, "yes"):
            b.open("yes", ctx.market, clock=ctx.clock,
                   reason=f"Win-prob +{vel*100:.0f}pts/{win}s, price {(mp-ap)*100:.0f}¢ behind, flow agrees")
            self._side = "yes"; self._entry_ts = ctx.now_ts
        elif vel <= -vmin and (ap - mp) >= gap and _flow_confirms(ctx, "no"):
            b.open("no", ctx.market, clock=ctx.clock,
                   reason=f"Win-prob {vel*100:.0f}pts/{win}s, price {(ap-mp)*100:.0f}¢ behind, flow agrees")
            self._side = "no"; self._entry_ts = ctx.now_ts


# ── 4. Run Momentum (RIDE an N-0 run; no model dependence) ────────────────────
# DATA-DRIVEN: backtesting 69 playoff games showed FADING runs loses (2% win,
# −$280); RIDING them wins (~65%, +$128). In playoff ball, runs continue. So this
# bets WITH the run by default (ride=True). ride=False reverts to the fade thesis.
class RunMomentum(Strategy):
    key = "run_momentum"
    label = "Run Momentum"
    description = ("Rides a team on an unanswered run (in playoff ball runs "
                   "continue, the market under-reacts). Guards against late-game "
                   "and bridged-period runs; exits on run break, profit, or stop.")
    needs = {"price", "playbyplay"}
    stake_frac = 0.05                 # net-negative after fees (Kelly 0) → minimal

    def __init__(self, params=None):
        super().__init__(params)
        self._faded_run = None        # run_team we faded
        self._run_seen = None
        self._run_start_period = None

    def evaluate(self, ctx):
        g, b, m = ctx.game, ctx.broker, ctx.market
        rt, rs = g.get("run_team"), (g.get("run_size") or 0)
        # track when a new run begins (for bridged-period detection)
        if rt != self._run_seen:
            self._run_seen, self._run_start_period = rt, g.get("period")

        thr_base = self.p("run_threshold", 8)
        thr = self.p("run_threshold_late", 10) if ctx.final_period else thr_base
        target, stop = self.p("revert_target", 0.04), self.p("hard_stop", 0.05)
        yb, ya = m.get("yes_bid"), m.get("yes_ask")

        if not b.flat:
            if self._force_flat(ctx, 90):
                self._faded_run = None
                return
            t = b.open_trade
            broke = (rt != self._faded_run or rs < thr_base)
            if t.side == "no":                       # want YES price to fall
                fav = (yb is not None and t.entry_price - yb >= target)
                adverse = (ya is not None and ya - t.entry_price >= stop)
            else:                                    # want YES price to rise
                fav = (ya is not None and ya - t.entry_price >= target)
                adverse = (yb is not None and t.entry_price - yb >= stop)
            if fav:
                b.close(m, clock=ctx.clock, reason=f"Reverted {target*100:.0f}¢ — taking profit"); self._faded_run = None
            elif adverse:
                b.close(m, clock=ctx.clock, reason=f"Hard stop {stop*100:.0f}¢ — run is real"); self._faded_run = None
            elif broke:
                b.close(m, clock=ctx.clock, reason="Run broke — exiting"); self._faded_run = None
            elif self._timeup(ctx, self.p("time_cap_s", 150)):
                b.close(m, clock=ctx.clock, reason="Time cap reached"); self._faded_run = None
            return

        # entry guards
        if not self._live(ctx) or not ctx.game_fresh:
            return
        if not rt or rs < thr:
            return
        if ctx.seconds_left is not None and ctx.seconds_left < 90:   # late-run = real, don't fade
            return
        if g.get("period") != self._run_start_period:               # bridged a period break
            return
        run_by_yes = ((rt == "home") == ctx.yes_is_home)
        # light sanity: price must have at least started moving toward the runner
        ref = _price_back(m, ctx.now_ts, self.p("spike_lookback_s", 75))
        cur = m.get("mid")
        if ref is not None and cur is not None:
            moved = (cur - ref) if run_by_yes else (ref - cur)   # + = toward runner
            if moved < self.p("spike_min", 0.0):
                return                              # price moving the wrong way — skip
            if moved < 0.01:
                return                              # nothing happening on the tape
        runner = ctx.yes_team if run_by_yes else _other(ctx)
        ride = self.p("ride", True)               # ride = bet WITH the run (default)
        if ride:
            side = "yes" if run_by_yes else "no"
            verb = "riding momentum"
        else:
            side = "no" if run_by_yes else "yes"
            verb = "fading overreaction"
        t = b.open(side, m, clock=ctx.clock,
                   reason=f"{runner} on {rs}-0 run, price spiked — {verb}")
        if t:
            self._faded_run = rt
            self._entry_ts = ctx.now_ts


# ── 5. Late-Game Favorite Lock ────────────────────────────────────────────────
class LateFav(Strategy):
    key = "late_fav"
    label = "Late-Game Favorite Lock"
    description = ("Late in a comfortable game, buys a strong favorite (model ≥85%) "
                   "that's still cheap (≤90¢); holds toward settlement but bails "
                   "fast if the live price drops (comeback before ESPN knows). "
                   "Highest-conviction, lowest-variance — sized larger.")
    needs = {"price", "winprob"}
    stake_frac = 0.35                 # ~100% win, near-zero downside; sized high

    def __init__(self, params=None):
        super().__init__(params)
        self._peak = None             # favorite's price peak since entry (yes terms)

    def _fav_price(self, ctx):
        t = ctx.broker.open_trade
        if not t:
            return None
        yb, ya = ctx.market.get("yes_bid"), ctx.market.get("yes_ask")
        return yb if t.side == "yes" else (None if ya is None else 1 - ya)

    def evaluate(self, ctx):
        g, b = ctx.game, ctx.broker
        mp, ip = ctx.model_p_yes, ctx.implied_p_yes
        fav, pmax, exitp = self.p("fav_prob", 0.85), self.p("price_max", 0.90), self.p("exit_prob", 0.75)

        if not b.flat:
            t = b.open_trade
            fp = self._fav_price(ctx)
            if fp is not None:
                self._peak = fp if self._peak is None else max(self._peak, fp)
            if self._force_flat(ctx, 60):
                self._peak = None
                return
            fav_price = (ip if t.side == "yes" else (1 - ip)) if ip is not None else None
            fav_model = mp if t.side == "yes" else (None if mp is None else 1 - mp)
            # take profit near the top
            if fav_price is not None and fav_price >= self.p("tp", 0.95):
                b.close(ctx.market, clock=ctx.clock, reason="Locked at 95¢ — taking it"); self._peak = None
            # comeback shows on price first — bail on a sharp live drop
            elif fp is not None and self._peak is not None and self._peak - fp >= self.p("drop_exit", 0.05):
                b.close(ctx.market, clock=ctx.clock, reason="Favorite price dropped 5¢ — bailing"); self._peak = None
            elif fav_model is not None and fav_model < exitp:
                b.close(ctx.market, clock=ctx.clock, reason=f"Lead evaporating (model {fav_model:.0%}) — bailing"); self._peak = None
            return

        # entry guards
        if not self._live(ctx) or not ctx.final_period or mp is None or ip is None:
            return
        lo, hi = self.p("window_lo", 60), self.p("window_hi", 300)
        if ctx.seconds_left is None or not (lo <= ctx.seconds_left <= hi):
            return
        ys, os = _yes_side_score(ctx)
        mins = ctx.seconds_left / 60.0
        # comeback abort: trailing team on a live run
        trailing = "away" if (ys > os) == ctx.yes_is_home else "home"
        if g.get("run_team") == trailing and (g.get("run_size") or 0) >= 8:
            return
        if mp >= fav and ip <= pmax and (ys - os) >= 3 * mins:
            b.open("yes", ctx.market, clock=ctx.clock,
                   reason=f"Late: {ctx.yes_team} model {mp:.0%}, lead structural, price {ip:.0%} — locking favorite")
            self._peak = ip
        elif (1 - mp) >= fav and (1 - ip) <= pmax and (os - ys) >= 3 * mins:
            b.open("no", ctx.market, clock=ctx.clock,
                   reason=f"Late: {_other(ctx)} model {(1-mp):.0%}, lead structural, price {(1-ip):.0%} — locking favorite")
            self._peak = 1 - ip


# ── 6. Spread Capture (LIVE ONLY) ─────────────────────────────────────────────
class SpreadCap(Strategy):
    key = "spread_cap"
    label = "Spread Capture"
    description = ("In a calm stretch with a wide spread and a fair mid, leans the "
                   "lopsided side of the book. Exploratory — you pay spread both "
                   "ways. Live-only.")
    needs = {"price", "orderflow"}
    stake_frac = 0.10                 # live-only, marginal/exploratory → conservative

    def evaluate(self, ctx):
        m, g, b = ctx.market, ctx.game, ctx.broker
        spread, imb, flow = m.get("spread"), (m.get("imbalance") or 0), (m.get("trade_flow") or 0)
        if not b.flat:
            t = b.open_trade
            yb, ya = m.get("yes_bid"), m.get("yes_ask")
            tp = self.p("tp", 0.03)
            took = (t.side == "yes" and yb is not None and yb - t.entry_price >= tp) or \
                   (t.side == "no" and ya is not None and t.entry_price - ya >= tp)
            if self._force_flat(ctx, 180):
                return
            if took:
                b.close(m, clock=ctx.clock, reason="Captured 3¢ — done")
            elif (m.get("spread") or 1) <= self.p("exit_spread", 0.02):
                b.close(m, clock=ctx.clock, reason="Spread re-tightened — edge gone")
            elif (g.get("run_size") or 0) >= 6:
                b.close(m, clock=ctx.clock, reason="Run started — calm stretch over")
            elif self._timeup(ctx, self.p("time_cap_s", 90)):
                b.close(m, clock=ctx.clock, reason="Time cap reached")
            return
        # entry guards
        if not self._live(ctx):
            return
        if ctx.final_period and ctx.seconds_left is not None and ctx.seconds_left <= 180:
            return                                  # spreads widen near settlement
        mp, mid = ctx.model_p_yes, m.get("mid")
        if spread is None or spread < self.p("min_spread", 0.04):
            return
        if (g.get("run_size") or 0) >= 6 or abs(flow) > self.p("max_flow", 30):
            return
        if mp is None or mid is None or abs(mp - mid) > self.p("fair_tol", 0.03):
            return
        tilt = self.p("imb", 0.25)
        if imb >= tilt:
            b.open("yes", m, clock=ctx.clock, reason=f"Wide spread {spread*100:.0f}¢, calm, book bid-heavy")
            self._entry_ts = ctx.now_ts
        elif imb <= -tilt:
            b.open("no", m, clock=ctx.clock, reason=f"Wide spread {spread*100:.0f}¢, calm, book ask-heavy")
            self._entry_ts = ctx.now_ts


# ── 7. Conviction + Flow gate (LIVE ONLY) ─────────────────────────────────────
# REWRITTEN after live data: the old scalp-the-convergence version lost −$9.36 in
# 17 trades on the SAME edge Conviction made +$11.27 on by holding. Lesson: with a
# persistent edge, HOLD to settlement — don't scalp (fees kill you). So this is now
# Conviction + an order-flow entry gate (only buy the cheap favorite when live flow
# agrees), holding to settlement and bailing if flow flips hard against.
class FlowConfirm(Strategy):
    key = "flow_confirm"
    label = "Conviction + Flow Gate"
    description = ("Buys the cheap model-favorite (like Conviction) ONLY when live "
                   "order flow agrees, then HOLDS to settlement; bails if the lead "
                   "collapses or flow flips hard against. Live-only.")
    needs = {"price", "winprob", "orderflow"}
    stake_frac = 0.15                 # validated pattern (hold), live-confirmed → modest+

    def __init__(self, params=None):
        super().__init__(params)
        self._pers = _Persist(2, self.p("persist_s", 20))
        self._against = 0

    def evaluate(self, ctx):
        m, b, mp, ap, ip = ctx.market, ctx.broker, ctx.model_p_yes, ctx.aligned_implied, ctx.implied_p_yes
        if not b.flat:
            t = b.open_trade
            fav_model = mp if t.side == "yes" else (None if mp is None else 1 - mp)
            fav_price = (ip if t.side == "yes" else (1 - ip)) if ip is not None else None
            if fav_price is not None and fav_price >= self.p("lock", 0.96):
                b.close(m, clock=ctx.clock, reason="Locked near settlement"); self._against = 0; return
            if fav_model is not None and fav_model < self.p("bail_prob", 0.65):
                b.close(m, clock=ctx.clock, reason=f"Lead collapsed (model {fav_model:.0%})"); self._against = 0; return
            # flow-specific value-add: exit if smart money flips against us 2 ticks
            self._against = self._against + 1 if not _flow_confirms(ctx, t.side) else 0
            if self._against >= 2:
                b.close(m, clock=ctx.clock, reason="Order flow flipped against us"); self._against = 0
            return
        if not self._live(ctx) or mp is None or ap is None:
            return
        fav_min, thr = self.p("fav_min", 0.70), self.p("edge", 0.06)
        if mp >= fav_min and (mp - ap) >= thr and _flow_confirms(ctx, "yes"):
            if self._pers.update(True, 1, ctx.model_ts, ctx.now_ts):
                b.open("yes", m, clock=ctx.clock,
                       reason=f"{ctx.yes_team} model {mp:.0%} vs {ap:.0%}, flow agrees — holding")
                self._pers.reset(); self._against = 0
        elif (1 - mp) >= fav_min and (ap - mp) >= thr and _flow_confirms(ctx, "no"):
            if self._pers.update(True, -1, ctx.model_ts, ctx.now_ts):
                b.open("no", m, clock=ctx.clock,
                       reason=f"{_other(ctx)} model {(1-mp):.0%} vs {(1-ap):.0%}, flow agrees — holding")
                self._pers.reset(); self._against = 0
        else:
            self._pers.reset()


# ── 8. Conviction Hold (fee-optimized generalization of Late-Fav) ─────────────
# Built FROM the cost data: fees are tiny at high prices and ZERO at settlement,
# and frequent trading near 50¢ is a fee massacre. So this buys the model-favored
# side ONLY when it's a strong favorite trading cheap, then HOLDS TO SETTLEMENT
# (one entry fee, no exit fee). Generalizes late_fav across the whole game.
class Conviction(Strategy):
    key = "conviction"
    label = "Conviction Hold"
    description = ("Buys a model-favored team (model ≥70%) when the aligned price "
                   "is meaningfully below the model, then HOLDS TO SETTLEMENT — "
                   "cheap entry fee, no exit fee. Bails only if the lead truly "
                   "collapses. Fee-optimized; the generalization of Late-Fav.")
    needs = {"price", "winprob"}
    stake_frac = 0.25                 # ~⅔ Kelly (full Kelly ≈0.37) — the real earner

    def __init__(self, params=None):
        super().__init__(params)
        self._pers = _Persist(2, self.p("persist_s", 20))

    def evaluate(self, ctx):
        b, mp, ap, ip = ctx.broker, ctx.model_p_yes, ctx.aligned_implied, ctx.implied_p_yes
        if not b.flat:
            t = b.open_trade
            fav_model = mp if t.side == "yes" else (None if mp is None else 1 - mp)
            fav_price = (ip if t.side == "yes" else (1 - ip)) if ip is not None else None
            # lock near the top (tiny fee, avoid the rare late collapse)
            if fav_price is not None and fav_price >= self.p("lock", 0.96):
                b.close(ctx.market, clock=ctx.clock, reason="Locked near settlement"); return
            # bail only on a real collapse (model says the lead is gone)
            if fav_model is not None and fav_model < self.p("bail_prob", 0.65):
                b.close(ctx.market, clock=ctx.clock, reason=f"Lead collapsed (model {fav_model:.0%}) — bailing"); return
            # otherwise HOLD — settlement is free and is the whole point
            return
        if not self._live(ctx) or mp is None or ap is None:
            return
        fav_min, thr = self.p("fav_min", 0.70), self.p("edge", 0.06)
        # YES is a model favorite trading cheap → buy YES and hold
        if mp >= fav_min and (mp - ap) >= thr:
            if self._pers.update(True, 1, ctx.model_ts, ctx.now_ts):
                b.open("yes", ctx.market, clock=ctx.clock,
                       reason=f"{ctx.yes_team} model {mp:.0%} but priced {ap:.0%} — buying cheap favorite, holding")
                self._pers.reset()
        # NO is a model favorite trading cheap → buy NO and hold
        elif (1 - mp) >= fav_min and (ap - mp) >= thr:
            if self._pers.update(True, -1, ctx.model_ts, ctx.now_ts):
                b.open("no", ctx.market, clock=ctx.clock,
                       reason=f"{_other(ctx)} model {(1-mp):.0%} but priced {(1-ap):.0%} — buying cheap favorite, holding")
                self._pers.reset()
        else:
            self._pers.reset()


# ── 9. Auto House — Claude-owned, auto-tuned (paper-only) ─────────────────────
# Same logic as Conviction, but its params are re-optimized from accumulated data
# by auto_tune.py with guardrails (only adopt if it beats current in backtest;
# versioned + changelogged). Runs in PARALLEL with the user's hand-built
# strategies for comparison. Never traded with real money.
class AutoHouse(Conviction):
    key = "auto_house"
    label = "Auto House (Claude-owned)"
    description = ("Claude-owned conviction-style model whose params auto_tune.py "
                   "re-optimizes from accumulated data (guarded, versioned). "
                   "Paper-only — never wired to real money.")
    stake_frac = 0.20


REGISTRY = {s.key: s for s in [
    EdgeNaive, ModelRevert, WPMomentum, RunMomentum, LateFav, SpreadCap,
    FlowConfirm, Conviction, AutoHouse]}

LIVE_ONLY = {k for k, s in REGISTRY.items() if "orderflow" in s.needs}

# ── versioned params (strategy_params.json) ──────────────────────────────────
# Tunable params + unit sizes live in strategy_params.json (versioned, with a
# changelog) so every change is tracked/reversible. Code defaults are the
# fallback. Edit via the review→approve loop in docs/LAB.md.
import json as _json
import os as _os
_PARAMS_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             "strategy_params.json")


def load_params():
    try:
        return _json.load(open(_PARAMS_PATH)).get("strategies", {})
    except Exception:
        return {}


def params_version():
    try:
        return _json.load(open(_PARAMS_PATH)).get("version")
    except Exception:
        return None


def make(key, overrides=None):
    """Build ONE strategy with its configured params (file → code-default
    fallback). `overrides` lets tuning/backtests inject param variants."""
    if key not in REGISTRY:
        raise KeyError(f"Unknown strategy '{key}'. Known: {list(REGISTRY)}")
    params = dict(load_params().get(key, {}))
    if overrides:
        params.update(overrides)
    s = REGISTRY[key](params=params)
    if "stake_frac" in params:
        s.stake_frac = params["stake_frac"]
    return s


def build(keys):
    return [make(k) for k in keys]
