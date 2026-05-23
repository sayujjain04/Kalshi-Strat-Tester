#!/usr/bin/env python3
"""
engine.py
──────────
Wires the data feeds, paper broker, strategies, and dashboard together. Two ways
to run:

  • LIVE    — connect to Kalshi WS + ESPN for an in-progress game, evaluate every
              strategy on each update, write the dashboard.
  • REPLAY  — reconstruct a finished game from Kalshi 1-min candles + ESPN
              play-by-play + win probability, and run the exact same strategies
              and dashboard at fast-forward speed.

Both build the same Context per step, so a strategy can't tell which mode it's
in (except that order-flow data is empty in replay — Kalshi doesn't publish
historical depth/tape).
"""
import threading, time
from datetime import datetime, timezone

from kalshi_client import KalshiClient, PROD, d, fp
from kalshi_feed import KalshiFeed
from espn_feed import ESPNFeed, espn_abbr
from paper_broker import Portfolio
from strategies import Context
import dashboard

_MONTHS = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05",
           "JUN": "06", "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10",
           "NOV": "11", "DEC": "12"}


# ── ticker parsing ────────────────────────────────────────────────────────────
def parse_ticker(ticker):
    """KXNBAGAME-26MAY22OKCSAS-OKC → date/away/home/yes_team/yes_is_home."""
    try:
        _, mid, yes_team = ticker.split("-")[:3]
    except ValueError:
        return None
    for mon, num in _MONTHS.items():
        if mon in mid:
            i = mid.index(mon)
            yr, rest = "20" + mid[:i], mid[i + 3:]
            day, teams = rest[:2], rest[2:]
            away, home = teams[:3], teams[3:]
            return {"date": f"{yr}{num}{day}", "away": away, "home": home,
                    "yes_team": yes_team, "yes_is_home": yes_team == home}
    return None


def _iso_to_unix(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def game_id(meta):
    """Readable per-game folder name, e.g. '20260522_OKC_SAS'."""
    return f"{meta['date']}_{meta['away']}_{meta['home']}"


# ── candles ─────────────────────────────────────────────────────────────────
def fetch_candles(client, ticker, start_ts, end_ts, interval=1):
    series = ticker.split("-")[0]
    data, err = client.get(
        f"/series/{series}/markets/{ticker}/candlesticks",
        {"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": interval})
    out = []
    for c in (data or {}).get("candlesticks", []):
        p = c.get("price") or {}
        yb = (c.get("yes_bid") or {}).get("close_dollars")
        ya = (c.get("yes_ask") or {}).get("close_dollars")
        out.append({"o": d(p.get("open_dollars")), "h": d(p.get("high_dollars")),
                    "l": d(p.get("low_dollars")), "c": d(p.get("close_dollars")),
                    "v": fp(c.get("volume_fp")), "ts": c.get("end_period_ts"),
                    "yb": d(yb), "ya": d(ya)})
    return [c for c in out if c["c"] is not None]


def market_from_candle(c):
    if not c:
        return {"connected": False, "yes_bid": None, "yes_ask": None, "mid": None,
                "last_price": None, "volume": None, "spread": None,
                "imbalance": 0.0, "trade_flow": 0.0, "trades": []}
    yb = c["yb"] if c["yb"] else (c["c"] - 0.005 if c["c"] else None)
    ya = c["ya"] if c["ya"] else (c["c"] + 0.005 if c["c"] else None)
    mid = (yb + ya) / 2 if (yb is not None and ya is not None) else c["c"]
    return {"connected": True, "yes_bid": yb, "yes_ask": ya, "mid": mid,
            "last_price": c["c"], "volume": c["v"],
            "spread": (ya - yb) if (yb is not None and ya is not None) else None,
            "imbalance": 0.0, "trade_flow": 0.0, "trades": []}


# ── shared: build context + view-model ───────────────────────────────────────
def _implied(market):
    return market.get("mid") if market.get("mid") is not None else market.get("last_price")


def _price_at(history, ts):
    """Mid price as of time `ts` (ms) from ascending (ts_ms, mid) history."""
    if not history or ts is None:
        return None
    out = None
    for t, mid in history:
        if t is not None and t <= ts:
            out = mid
        else:
            break
    return out


def _secs_left(clock_str):
    """ESPN clock 'M:SS' → seconds remaining in the period."""
    try:
        mm, ss = str(clock_str).split(":")
        return int(mm) * 60 + float(ss)
    except Exception:
        return None


def make_context(strat, market, game, meta, broker, is_replay, now_ts=None,
                 game_fresh=True):
    yih = meta["yes_is_home"]
    wp_home = game.get("win_prob_home")
    model = None if wp_home is None else (wp_home if yih else 1 - wp_home)
    implied = _implied(market)
    model_ts = game.get("win_prob_ts")
    if is_replay:
        # in replay the price is already matched to the play's wallclock
        aligned = implied
        now_ts = now_ts or model_ts
        age = 0.0
    else:
        now_ts = now_ts or int(time.time() * 1000)
        aligned = _price_at(market.get("history") or [], model_ts)
        if aligned is None:
            aligned = implied
        age = ((now_ts - model_ts) / 1000.0) if model_ts else None

    period = game.get("period") or 0
    secs_left = _secs_left(game.get("clock"))
    final_period = isinstance(period, int) and period >= 4   # 4th or any OT
    near_settlement = final_period and secs_left is not None and secs_left <= 60
    return Context(market=market, game=game, yes_team=meta["yes_team"],
                   yes_is_home=yih, implied_p_yes=implied, model_p_yes=model,
                   aligned_implied=aligned, model_ts=model_ts, now_ts=now_ts,
                   model_age_s=age, status=game.get("status", "in"),
                   seconds_left=secs_left, final_period=final_period,
                   near_settlement=near_settlement, game_fresh=game_fresh,
                   clock=f"Q{period or '?'} {game.get('clock','')}",
                   broker=broker, is_replay=is_replay)


def build_vm(meta, market, game, candles, model_series, plays, portfolio,
             mode, refresh):
    wp_home = game.get("win_prob_home")
    model = None if wp_home is None else (wp_home if meta["yes_is_home"] else 1 - wp_home)
    return {
        "mode": mode, "refresh": refresh, "yes_team": meta["yes_team"],
        "game": game, "market": market,
        "implied_p_yes": _implied(market), "model_p_yes": model,
        "candles": candles, "model_series": model_series, "plays": plays,
        "leaderboard": portfolio.leaderboard(market),
        "journal": portfolio.journal(),
        "generated": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    }


# ── discovery ─────────────────────────────────────────────────────────────────
def list_live_games(client, log=print):
    """All NBA games on Kalshi today-ish, annotated with ESPN status/score."""
    markets = client.markets(series_ticker="KXNBAGAME", status="open", limit=200)
    games = {}
    for m in markets:
        p = parse_ticker(m["ticker"])
        if not p:
            continue
        key = (p["date"], p["away"], p["home"])
        g = games.setdefault(key, {**p, "tickers": []})
        g["tickers"].append(m["ticker"])
    out = []
    for (date, away, home), g in games.items():
        eid = ESPNFeed.find_event_id(date, away, home, log=lambda *_: None)
        status, score = "pre", {"home": 0, "away": 0}
        if eid:
            status, score = _espn_status(eid)
        # canonical ticker = the AWAY team's YES market
        canonical = next((t for t in g["tickers"] if t.endswith(away)), g["tickers"][0])
        out.append({"ticker": canonical, "date": date, "away": away, "home": home,
                    "yes_team": parse_ticker(canonical)["yes_team"],
                    "espn_id": eid, "status": status, "score": score})
    order = {"in": 0, "pre": 1, "post": 2}
    out.sort(key=lambda x: (order.get(x["status"], 3), x["date"]))
    return out


def _espn_status(eid):
    import requests
    try:
        r = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
                         params={"event": eid}, timeout=12,
                         headers={"User-Agent": "r/2.0"}).json()
        comp = r.get("header", {}).get("competitions", [{}])[0]
        st = comp.get("status", {}).get("type", {}).get("state", "pre")
        sc = {"home": 0, "away": 0}
        for c in comp.get("competitors", []):
            side = "home" if c.get("homeAway") == "home" else "away"
            sc[side] = int(c.get("score") or 0)
        return st, sc
    except Exception:
        return "pre", {"home": 0, "away": 0}


def list_recent_finished(days=4, log=print):
    """Finished NBA games over the last few days, for replay selection."""
    import requests
    ESPN = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    out = []
    for back in range(days):
        dt = datetime.now(timezone.utc)
        dt = dt.fromordinal(dt.toordinal() - back)
        ds = dt.strftime("%Y%m%d")
        try:
            r = requests.get(f"{ESPN}/scoreboard", params={"dates": ds}, timeout=12,
                             headers={"User-Agent": "r/2.0"}).json()
        except Exception:
            continue
        for ev in r.get("events", []):
            comp = ev["competitions"][0]
            if comp["status"]["type"]["state"] != "post":
                continue
            cs = {c["homeAway"]: c for c in comp["competitors"]}
            out.append({
                "espn_id": ev["id"], "date": ds,
                "away": cs["away"]["team"]["abbreviation"],
                "home": cs["home"]["team"]["abbreviation"],
                "away_score": cs["away"].get("score"), "home_score": cs["home"].get("score"),
                "label": f'{cs["away"]["team"]["abbreviation"]} {cs["away"].get("score")} @ '
                         f'{cs["home"]["team"]["abbreviation"]} {cs["home"].get("score")} ({ds})',
            })
    return out


def kalshi_ticker_for(client, date, espn_away, espn_home):
    """Find the finalized Kalshi market for an ESPN game (matches on team codes)."""
    markets = client.markets(series_ticker="KXNBAGAME", status="settled", limit=200) \
        + client.markets(series_ticker="KXNBAGAME", status="finalized", limit=200)
    for m in markets:
        p = parse_ticker(m["ticker"])
        if not p or p["date"] != date:
            continue
        # Kalshi codes → ESPN codes, compare
        if {espn_abbr(p["away"]), espn_abbr(p["home"])} == {espn_away, espn_home} \
                and m["ticker"].endswith(p["away"]):
            return m["ticker"]
    return None


# ── LIVE engine ───────────────────────────────────────────────────────────────
class LiveEngine:
    def __init__(self, ticker, espn_id, strategies, out_path, refresh=5, log=print):
        self.meta = parse_ticker(ticker)
        self.ticker = ticker
        self.espn_id = espn_id
        self.strategies = strategies
        self.out_path = out_path
        self.refresh = refresh
        self.log = log
        self.client = KalshiClient(PROD)
        self.portfolio = Portfolio(100.0, log=log)
        for s in strategies:
            s.account = self.portfolio.account_for(s.label, s.stake_frac)
        self.candles = []
        self.model_series = []
        self.plays = []
        self._stop = False
        self._settled = False
        import tradelog
        self._gdir = tradelog.game_dir(game_id(self.meta))
        self._declog = tradelog.DecisionLogger(self._gdir, "paper")
        self._tickrec = tradelog.MarketRecorder(self._gdir, heartbeat_s=30)
        self._tapelog = tradelog.TradeTapeLogger(self._gdir)

    def _on_plays(self, gs, new):
        import tradelog
        for p in new:
            rec = {"period": (p.get("period") or {}).get("number", "?"),
                   "clock": (p.get("clock") or {}).get("displayValue", ""),
                   "text": p.get("text", "")}
            self.plays.append(rec)
            # full ESPN play-by-play log: exact score + win prob + text, every play
            tradelog.append_line(self._gdir, "plays.jsonl", {
                **rec,
                "home_score": p.get("homeScore"), "away_score": p.get("awayScore"),
                "scoring_play": p.get("scoringPlay"), "wallclock": p.get("wallclock"),
                "win_prob_home": gs.win_prob_home,
            })

    def _candle_poller(self):
        while not self._stop:
            now = int(time.time())
            cs = fetch_candles(self.client, self.ticker, now - 4 * 3600, now, interval=1)
            if cs:
                self.candles = cs
            time.sleep(30)

    def run(self, stop_on_post=False):
        self.market_state = KalshiFeed(self.ticker, PROD, self.log).start()
        # poll ESPN every 5s (not 15) — shrinks every lag window by ~2/3
        espn = ESPNFeed(self.espn_id, self.meta["away"], self.meta["home"],
                        poll_secs=5, log=self.log, on_new_plays=self._on_plays)
        self.game_state = espn.start()
        post_seen = 0
        threading.Thread(target=self._candle_poller, daemon=True).start()
        self.log(f"LIVE — {self.meta['away']} @ {self.meta['home']} | "
                 f"strategies: {', '.join(s.label for s in self.strategies)}")

        last_model, last_sig = None, None
        try:
            while not self._stop:
                market = self.market_state.snapshot()
                game = self.game_state.snapshot()
                # dead-data guard: game-derived signals only re-fire when ESPN
                # actually advanced (its timestamp / score / clock changed)
                sig = (game.get("win_prob_ts"), game["score"]["home"],
                       game["score"]["away"], game.get("clock"))
                game_fresh = sig != last_sig
                last_sig = sig
                # shared signal context (same for all strategies this tick)
                sctx = make_context(self.strategies[0], market, game, self.meta,
                                    self.strategies[0].account, is_replay=False,
                                    game_fresh=game_fresh)
                signal = {"model_p_yes": sctx.model_p_yes,
                          "implied_p_yes": sctx.implied_p_yes,
                          "aligned_implied": sctx.aligned_implied,
                          "model_age_s": sctx.model_age_s,
                          "edge": (None if sctx.model_p_yes is None or sctx.aligned_implied is None
                                   else round(sctx.model_p_yes - sctx.aligned_implied, 4))}
                for s in self.strategies:
                    try:
                        s.evaluate(make_context(s, market, game, self.meta,
                                                s.account, is_replay=False,
                                                game_fresh=game_fresh))
                    except Exception as e:
                        self.log(f"{s.label} error: {e}")
                # when the game ends, settle any still-open paper positions at the
                # real $1/$0 outcome so P&L is realized (and logged), not left "open"
                if game.get("status") == "post" and not self._settled:
                    self._settle_open(game, market)
                    self._settled = True
                # log every strategy open/close (raw market + signal + sim) and
                # the full raw market/game tick stream for later re-simulation
                self._declog.flush(self.portfolio.accounts, game, market, signal)
                self._tickrec.flush(market, game)
                self._tapelog.flush(market)
                # track model probability series for the chart
                wp = game.get("win_prob_home")
                if wp is not None and wp != last_model:
                    self.model_series.append(wp if self.meta["yes_is_home"] else 1 - wp)
                    last_model = wp
                vm = build_vm(self.meta, market, game, self.candles, self.model_series,
                              self.plays, self.portfolio, "LIVE", self.refresh)
                dashboard.write(self.out_path, vm)
                # headless: exit a bit after the game finalizes (let it settle/log)
                if stop_on_post and game.get("status") == "post":
                    post_seen += 1
                    if post_seen >= 5:
                        self.log("Game finished — stopping (headless).")
                        break
                time.sleep(2)
        except KeyboardInterrupt:
            self.log("Stopped.")
        finally:
            self._save_meta()

    def _settle_open(self, game, market):
        """Close any open paper position at the final $1/$0 outcome."""
        sc = game.get("score") or {}
        if sc.get("home") is None or sc.get("home") == sc.get("away"):
            return
        home_won = sc["home"] > sc["away"]
        yes_won = home_won if self.meta["yes_is_home"] else not home_won
        for s in self.strategies:
            if not s.account.flat:
                s.account.close(market, clock="FINAL",
                                reason="Game over — settled", settle_yes=yes_won)

    def _save_meta(self):
        import tradelog
        g = self.game_state.snapshot() if getattr(self, "game_state", None) else {}
        m = self.market_state.snapshot() if getattr(self, "market_state", None) else {}
        tradelog.save_meta(self._gdir, {
            "game_id": game_id(self.meta), "ticker": self.ticker, "mode": "paper",
            "away": self.meta["away"], "home": self.meta["home"], "date": self.meta["date"],
            "yes_team": self.meta["yes_team"],
            "final_score": g.get("score"), "final_status": g.get("status"),
            "strategies": [{"strategy": s.label, "equity": round(s.account.equity(m), 2),
                            "trades": len(s.account.closed)} for s in self.strategies],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        })
        # append each strategy's outcome to the performance-history ledger
        import strategies as _strat
        pv = _strat.params_version()
        gid = game_id(self.meta)
        for s in self.strategies:
            cl = s.account.closed
            tradelog.append_result({
                "source": "live", "game_id": gid, "strategy": s.label, "key": s.key,
                "params_version": pv, "net_pnl": round(s.account.equity(m) - 100, 2),
                "trades": len(cl), "wins": sum(1 for t in cl if t.result == "WIN"),
                "losses": sum(1 for t in cl if t.result == "LOSS"),
                "final_score": g.get("score"),
            })


# ── REPLAY ────────────────────────────────────────────────────────────────────
def fetch_replay_data(espn_id, ticker, client=None):
    """Pull a finished game's plays + win-prob + candles. Returns dict or None."""
    import requests
    client = client or KalshiClient(PROD)
    ESPN = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    summ = requests.get(f"{ESPN}/summary", params={"event": espn_id}, timeout=20,
                        headers={"User-Agent": "r/2.0"}).json()
    plays = summ.get("plays") or []
    if not plays:
        return None
    wp_by_id = {w.get("playId"): w.get("homeWinPercentage")
                for w in (summ.get("winprobability") or [])}
    times = [t for t in (_iso_to_unix(p.get("wallclock")) for p in plays) if t]
    candles = fetch_candles(client, ticker, min(times) - 300, max(times) + 300, 1) \
        if times else []
    return {"plays": plays, "wp_by_id": wp_by_id, "candles": candles, "times": times}


def simulate(meta, data, strategies, frame_cb=None, log=lambda *a: None, slippage=None):
    """
    Core headless replay loop. Steps a finished game's plays through the
    strategies on $100 each and returns (portfolio, last_market). `frame_cb`, if
    given, is called each step for live dashboarding; backtests pass None.
    """
    plays, wp_by_id = data["plays"], data["wp_by_id"]
    candles_all, times = data["candles"], data["times"]
    import paper_broker
    slip = paper_broker.DEFAULT_SLIPPAGE if slippage is None else slippage
    portfolio = Portfolio(100.0, log=log, slippage=slip)
    for s in strategies:
        s.account = portfolio.account_for(s.label, s.stake_frac)
    feed = ESPNFeed("", meta["away"], meta["home"])   # reuse run/score logic only
    model_series, play_log, last_wp = [], [], None

    def candle_at(t):
        c = None
        for cc in candles_all:
            if cc["ts"] and cc["ts"] <= t:
                c = cc
            else:
                break
        return c or (candles_all[0] if candles_all else None)

    def candles_upto(t):
        return [cc for cc in candles_all if cc["ts"] and cc["ts"] <= t] or candles_all[:1]

    for i in range(1, len(plays) + 1):
        play = plays[i - 1]
        feed._ingest(plays[:i], {})
        t = _iso_to_unix(play.get("wallclock")) or (times[0] if times else time.time())
        t_ms = int(t * 1000)
        wp = wp_by_id.get(play.get("id"), last_wp)
        if wp is not None:
            feed.set_win_prob(wp, t_ms, (play.get("clock") or {}).get("displayValue", ""))
            last_wp = wp
            model_series.append(wp if meta["yes_is_home"] else 1 - wp)
        game = feed.state.snapshot()
        market = market_from_candle(candle_at(t))
        market["history"] = [(cc["ts"] * 1000, cc["c"]) for cc in candles_upto(t)
                             if cc["ts"] and cc["c"] is not None]
        play_log.append({"period": (play.get("period") or {}).get("number", "?"),
                         "clock": (play.get("clock") or {}).get("displayValue", ""),
                         "text": play.get("text", "")})
        for s in strategies:
            try:
                s.evaluate(make_context(s, market, game, meta, s.account,
                                        is_replay=True, now_ts=t_ms, game_fresh=True))
            except Exception as e:
                log(f"{s.label} error: {e}")
        if frame_cb:
            frame_cb(i, len(plays), meta, market, game, candles_upto(t),
                     model_series, play_log, portfolio)

    final = feed.state.snapshot()
    yes_won = None
    if final["score"]["home"] != final["score"]["away"]:
        home_won = final["score"]["home"] > final["score"]["away"]
        yes_won = home_won if meta["yes_is_home"] else not home_won
    last_market = market_from_candle(candles_all[-1] if candles_all else None)
    for s in strategies:
        if not s.account.flat:
            s.account.close(last_market, clock="FINAL",
                            reason="Game over — settled", settle_yes=yes_won)
    final["status"] = "post"
    return portfolio, last_market, model_series, play_log, final, candles_all


def run_replay(espn_id, ticker, strategies, out_path, log=print,
               step_delay=0.04, draw_every=6, refresh=2, write_dashboard=True):
    meta = parse_ticker(ticker)
    data = fetch_replay_data(espn_id, ticker)
    if not data:
        log("Replay: no play-by-play for that game."); return None
    log(f"REPLAY — {meta['away']} @ {meta['home']} | {len(data['plays'])} plays, "
        f"{len(data['candles'])} price bars | strategies: {', '.join(s.label for s in strategies)}")

    def frame_cb(i, total, meta, market, game, cu, ms, pl, pf):
        if write_dashboard and (i % draw_every == 0 or i == total):
            dashboard.write(out_path, build_vm(meta, market, game, cu, ms, pl, pf,
                                               "REPLAY", refresh))
        if step_delay:
            time.sleep(step_delay)

    portfolio, last_market, ms, pl, final, candles_all = simulate(
        meta, data, strategies, frame_cb=frame_cb, log=log)
    if write_dashboard:
        dashboard.write(out_path, build_vm(meta, last_market, final, candles_all,
                                           ms, pl, portfolio, "REPLAY", refresh))
        log("Replay complete.")
        for s in portfolio.leaderboard(last_market):
            log(f"  {s['strategy']:22} equity ${s['equity']:.2f}  "
                f"({s['wins']}W/{s['losses']}L)")
    return portfolio, last_market
