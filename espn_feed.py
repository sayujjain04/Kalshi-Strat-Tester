#!/usr/bin/env python3
"""
espn_feed.py
─────────────
Polls ESPN's free NBA endpoints for live play-by-play and maintains a
thread-safe GameState (score, period, clock, current scoring run).

ESPN exposes:
  • /scoreboard?dates=YYYYMMDD   → find a game's event id from team abbrevs
  • /summary?event=<id>          → full play-by-play (each play carries the
                                    running homeScore/awayScore, period, clock)

Strategies that need game context read GameState; the run detector here turns
the raw play stream into a "team X is on an N-0 run" signal that fade/momentum
strategies key off of.
"""
import threading, time
from datetime import datetime, timezone

import requests

ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba"

# Kalshi 3-letter code → ESPN abbreviation (mostly identical; these differ)
TEAM_MAP = {
    "BRK": "BKN", "GSW": "GS", "NOR": "NO", "NYK": "NY",
    "PHX": "PHX", "SAS": "SA", "UTA": "UTAH",
}


def espn_abbr(kalshi_code):
    return TEAM_MAP.get(kalshi_code, kalshi_code)


def _wallclock_ms(s):
    """ESPN play wallclock ISO ('2026-05-21T23:40:00Z') → epoch ms."""
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


class GameState:
    def __init__(self, away, home):
        self.lock = threading.Lock()
        self.away = away
        self.home = home
        self.score = {"home": 0, "away": 0}
        self.period = 0
        self.clock = ""
        self.status = "pre"          # pre | in | post
        self.run_team = None         # "home" | "away" | None
        self.run_size = 0
        self.last_play = ""
        self.processed = 0           # plays consumed so far
        self.connected = False
        self.win_prob_home = None    # ESPN model P(home win), 0..1, updates per play
        self.win_prob_ts = None      # ms timestamp the win-prob is valid for (play wallclock)
        self.wp_history = []         # [(ts_ms, win_prob_home)] — timestamped for velocity

    def model_p_yes(self, yes_is_home):
        """ESPN model probability that the Kalshi YES side wins."""
        if self.win_prob_home is None:
            return None
        return self.win_prob_home if yes_is_home else 1.0 - self.win_prob_home

    def snapshot(self):
        with self.lock:
            return {
                "away": self.away, "home": self.home, "score": dict(self.score),
                "period": self.period, "clock": self.clock, "status": self.status,
                "run_team": self.run_team, "run_size": self.run_size,
                "last_play": self.last_play, "connected": self.connected,
                "win_prob_home": self.win_prob_home,
                "win_prob_ts": self.win_prob_ts,
                "wp_history": list(self.wp_history),
            }


class ESPNFeed:
    def __init__(self, espn_id, away, home, poll_secs=20, log=print,
                 on_new_plays=None):
        """on_new_plays(GameState, list_of_new_plays) fires after each poll."""
        self.espn_id = espn_id
        self.state = GameState(away, home)
        self.poll_secs = poll_secs
        self.log = log
        self.on_new_plays = on_new_plays
        self.sess = requests.Session()
        self.sess.headers["User-Agent"] = "KalshiResearch/2.0"
        self._stop = False

    # ----- discovery -----
    @staticmethod
    def find_event_id(date_str, away, home, log=print):
        a, h = espn_abbr(away), espn_abbr(home)
        try:
            r = requests.get(f"{ESPN_BASE}/scoreboard", params={"dates": date_str},
                             timeout=12)
            data = r.json() if r.status_code == 200 else {}
        except Exception as e:
            log(f"ESPN scoreboard error: {e}")
            return None
        for ev in data.get("events", []):
            comp = ev.get("competitions", [{}])[0]
            abbs = [c.get("team", {}).get("abbreviation", "")
                    for c in comp.get("competitors", [])]
            if a in abbs and h in abbs:
                return ev["id"]
        return None

    # ----- run loop -----
    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self.state

    def stop(self):
        self._stop = True

    def _fetch_plays(self):
        try:
            r = self.sess.get(f"{ESPN_BASE}/summary",
                              params={"event": self.espn_id}, timeout=15)
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get("plays", []), data
        except Exception as e:
            self.log(f"ESPN poll error: {e}")
            return None

    def _loop(self):
        with self.state.lock:
            self.state.connected = True
        self.log(f"ESPN poller started (event {self.espn_id}, every {self.poll_secs}s)")
        while not self._stop:
            res = self._fetch_plays()
            if res:
                plays, raw = res
                new = self._ingest(plays, raw)
                if new and self.on_new_plays:
                    try:
                        self.on_new_plays(self.state, new)
                    except Exception as e:
                        self.log(f"strategy on_play error: {e}")
            time.sleep(self.poll_secs)

    def _ingest(self, plays, raw):
        """Update score/run from any plays we haven't seen. Returns new plays."""
        s = self.state
        with s.lock:
            start = s.processed
        new_plays = plays[start:]
        if not new_plays and plays:
            return []

        # game status from header
        status = "in"
        try:
            comp = raw.get("header", {}).get("competitions", [{}])[0]
            st = comp.get("status", {}).get("type", {}).get("state")
            status = {"pre": "pre", "in": "in", "post": "post"}.get(st, "in")
        except Exception:
            pass

        # ESPN live win probability — last point carries the current value
        wp_home = None
        wp = raw.get("winprobability") or []
        if wp:
            try:
                wp_home = float(wp[-1].get("homeWinPercentage"))
            except (TypeError, ValueError):
                wp_home = None

        # wallclock (ms) of the latest play — when the win-prob is actually valid
        last_ts = None
        for p in new_plays:
            wc = _wallclock_ms(p.get("wallclock"))
            if wc:
                last_ts = wc
        if last_ts is None:
            last_ts = int(time.time() * 1000)

        with s.lock:
            score = dict(s.score)
            run_team, run_size = s.run_team, s.run_size
            for p in new_plays:
                h, a = p.get("homeScore"), p.get("awayScore")
                if h is None or a is None:
                    continue
                h, a = int(h), int(a)
                dh, da = h - score["home"], a - score["away"]
                if dh > 0 and da == 0:
                    run_size = run_size + dh if run_team == "home" else dh
                    run_team = "home"
                elif da > 0 and dh == 0:
                    run_size = run_size + da if run_team == "away" else da
                    run_team = "away"
                elif dh > 0 and da > 0:
                    run_team, run_size = None, 0
                score["home"], score["away"] = h, a
                per = p.get("period") or {}
                s.period = per.get("number", s.period) if isinstance(per, dict) else s.period
                s.clock = (p.get("clock") or {}).get("displayValue", s.clock)
                s.last_play = (p.get("text") or "")[:90]
            s.score = score
            s.run_team, s.run_size = run_team, run_size
            s.status = status
            s.processed = len(plays)
            if wp_home is not None and wp_home != s.win_prob_home:
                s.win_prob_home = wp_home
                s.win_prob_ts = last_ts
                s.wp_history.append((last_ts, wp_home))
        return new_plays

    def set_win_prob(self, wp_home, ts_ms, clock_label=""):
        """Used by replay mode to inject a known win-probability point at a time."""
        s = self.state
        with s.lock:
            if wp_home is not None:
                s.win_prob_home = wp_home
                s.win_prob_ts = ts_ms
                s.clock = clock_label or s.clock
                s.wp_history.append((ts_ms, wp_home))
