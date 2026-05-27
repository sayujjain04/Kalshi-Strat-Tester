#!/usr/bin/env python3
"""
boards.py — the founder's command center.

Generates everything under docs/ (served by GitHub Pages):
  docs/index.html            the board: lab summary, live/today games, strategy table
  docs/strategy/<key>.html   per-strategy detail: equity curve, per-game results,
                             condition breakdowns (edge/quarter/side/league), params
  docs/games/<id>.html       order-flow shards (via shards.py), one per captured game

Board state (which strategy is on DEV / PAPER / LIVE / PAST + live funding) lives in
boards.json.

    python3 boards.py            # full build: board + all detail pages + all shards
    python3 boards.py --quick    # board + detail + only changed/live shards (daemon push)
    python3 boards.py --move conviction LIVE
    python3 boards.py --promote conviction 100      # PAPER→LIVE, fund $100
    python3 boards.py --retire model_revert
"""
import glob, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone

import strategies as strat
import analyze
import shards

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "boards.json")
GAMES = os.path.join(ROOT, "data", "games")
LEDGER = os.path.join(ROOT, "data", "results", "strategy_history.jsonl")
DOCS = os.path.join(ROOT, "docs")
INDEX = os.path.join(DOCS, "index.html")
STRATDIR = os.path.join(DOCS, "strategy")
FLOOR = 0.50      # halt at −50% of a live allocation
STAGE_ORDER = {"LIVE": 0, "PAPER": 1, "DEV": 2, "PAST": 3}


# ── board state ───────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"DEV": [], "PAPER": list(strat.REGISTRY), "LIVE": [], "PAST": [],
            "funding": {}}


def save_state(s):
    json.dump(s, open(STATE, "w"), indent=2)


def move(strategy, board, fund=None):
    s = load_state()
    for b in ("DEV", "PAPER", "LIVE", "PAST"):
        if strategy in s.get(b, []):
            s[b].remove(strategy)
    s.setdefault(board, []).append(strategy)
    if fund is not None:
        s.setdefault("funding", {})[strategy] = fund
    save_state(s)
    print(f"{strategy} → {board}" + (f" (funded ${fund})" if fund is not None else ""))


# ── helpers ─────────────────────────────────────────────────────────────────
def _ledger():
    rows = []
    if os.path.exists(LEDGER):
        for l in open(LEDGER):
            l = l.strip()
            if not l:
                continue
            try:
                rows.append(json.loads(l))
            except Exception:
                pass
    return rows


def _label2key():
    return {cls.label: k for k, cls in strat.REGISTRY.items()}


def _key2stage(state):
    out = {}
    for stage in ("LIVE", "PAPER", "DEV", "PAST"):
        for k in state.get(stage, []):
            out[k] = stage
    return out


def _gid_teams(gid):
    parts = gid.split("_")
    rest = parts[2:] if (len(parts) >= 2 and parts[1] in analyze._LEAGUES) else parts[1:]
    return (rest[0], rest[1]) if len(rest) >= 2 else ("?", "?")


def _game_dirs():
    return [d for d in sorted(glob.glob(os.path.join(GAMES, "*")))
            if os.path.isdir(d) and os.path.exists(os.path.join(d, "ticks.jsonl"))]


def _last_tick(game_dir):
    p = os.path.join(game_dir, "ticks.jsonl")
    last = None
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line:
                last = line
    try:
        return json.loads(last) if last else {}
    except Exception:
        return {}


# ── stats from the ledger ─────────────────────────────────────────────────────
def compute_stats():
    """Per-strategy: forward (live) record with equity curve + per-game rows, and
    the latest backtest snapshot. Keyed by strategy key."""
    rows = sorted(_ledger(), key=lambda r: r.get("ts") or "")
    l2k = _label2key()
    live, bt, curve = {}, {}, defaultdict(list)
    for r in rows:
        key = r.get("key") or l2k.get(r.get("strategy"), r.get("strategy"))
        if r.get("source") == "live":
            a = live.setdefault(key, {"games": 0, "net": 0.0, "w": 0, "l": 0,
                                      "trades": 0, "best": None, "worst": None,
                                      "pergame": []})
            net = r.get("net_pnl") or 0
            a["games"] += 1
            a["net"] += net
            a["w"] += r.get("wins") or 0
            a["l"] += r.get("losses") or 0
            a["trades"] += r.get("trades") or 0
            a["best"] = net if a["best"] is None else max(a["best"], net)
            a["worst"] = net if a["worst"] is None else min(a["worst"], net)
            a["pergame"].append({"gid": r.get("game_id"), "net": net,
                                 "trades": r.get("trades") or 0,
                                 "w": r.get("wins") or 0, "l": r.get("losses") or 0,
                                 "ts": r.get("ts")})
            curve[key].append(a["net"])           # cumulative net after this game
        elif r.get("source") == "backtest":
            bt[key] = r
    return live, bt, curve


def recent_games(limit=8):
    out = []
    for d in reversed(_game_dirs()):
        gid = os.path.basename(d)
        meta = {}
        mp = os.path.join(d, "meta.json")
        if os.path.exists(mp):
            try:
                meta = json.load(open(mp))
            except Exception:
                meta = {}
        away = meta.get("away") or _gid_teams(gid)[0]
        home = meta.get("home") or _gid_teams(gid)[1]
        league = analyze.league_of_gid(gid)
        g = {"id": gid, "away": away, "home": home, "league": league}
        if meta.get("final_score") or meta.get("final_status") == "post":
            g["status"] = "FINAL"
            g["score"] = meta.get("final_score") or {}
            tops = sorted(meta.get("strategies", []),
                          key=lambda s: s.get("equity", 0), reverse=True)
            if tops:
                t = tops[0]
                g["top"] = {"name": t.get("strategy"), "pnl": (t.get("equity", 100) - 100),
                            "n": sum(1 for s in meta.get("strategies", []) if s.get("trades"))}
        else:                                     # in progress — read the last tick
            gs = (_last_tick(d).get("game") or {})
            st = gs.get("status")
            g["status"] = "LIVE" if st == "in" else ("PRE" if st == "pre" else "LIVE")
            g["score"] = gs.get("score") or {}
            g["period"], g["clock"] = gs.get("period"), gs.get("clock")
        out.append(g)
        if len(out) >= limit:
            break
    return out


def data_inventory(bt):
    bt_games = 0
    for r in bt.values():
        m = re.search(r"(\d+)", r.get("game_id", "") or "")
        if m:
            bt_games = max(bt_games, int(m.group(1)))
    by_league, captured, ndec = defaultdict(int), 0, 0
    for d in _game_dirs():
        captured += 1
        by_league[analyze.league_of_gid(os.path.basename(d))] += 1
        pdec = os.path.join(d, "paper_decisions.jsonl")
        if os.path.exists(pdec):
            ndec += sum(1 for _ in open(pdec))
    return {"backtest": bt_games, "captured": captured,
            "by_league": dict(by_league), "decisions": ndec}


RESEARCH = os.path.join(ROOT, "data", "research")


def research_log(n=14):
    p = os.path.join(RESEARCH, "log.jsonl")
    rows = []
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows[-n:][::-1]


def _ago(iso):
    """Humanize an ISO timestamp → 'just now' / '37m ago' / '3h ago' / '2d ago'."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        s = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return "?"
    if s < 90:        return "just now"
    if s < 5400:      return f"{int(s/60)}m ago"
    if s < 172800:    return f"{int(s/3600)}h ago"
    return f"{int(s/86400)}d ago"


def last_iteration(max_gap_min=60):
    """The most recent cluster of research-log entries = the last iteration's decisions.
    Entries from one run land within minutes of each other; a gap > max_gap_min starts a
    new iteration. Returns (when_iso, [entries newest-first])."""
    p = os.path.join(RESEARCH, "log.jsonl")
    rows = []
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    rows = [r for r in rows if r.get("ts")]
    if not rows:
        return None, []
    rows.sort(key=lambda r: r["ts"])
    cluster = [rows[-1]]
    for r in reversed(rows[:-1]):
        try:
            gap = (datetime.fromisoformat(cluster[-1]["ts"].replace("Z", "+00:00"))
                   - datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))).total_seconds()
        except Exception:
            break
        if gap <= max_gap_min * 60:
            cluster.append(r)
        else:
            break
    # cluster was built newest→oldest; its last element is the iteration's start time
    return cluster[-1]["ts"], cluster  # (when_started, entries newest-first)


def open_questions():
    p = os.path.join(ROOT, "docs", "OPEN_QUESTIONS.md")
    out, in_open = [], False
    if os.path.exists(p):
        for line in open(p):
            s = line.strip()
            if s.startswith("## Open"):
                in_open = True; continue
            if s.startswith("## ") and in_open:
                break
            if in_open and s.startswith("- [ ]"):
                out.append(s[5:].strip().lstrip("*").strip())
    return out


def research_spend(month=None):
    p = os.path.join(RESEARCH, "credits.jsonl")
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    t = 0.0
    if os.path.exists(p):
        for line in open(p):
            try:
                r = json.loads(line)
                if r.get("month") == month:
                    t += r.get("cost_usd", 0) or 0
            except Exception:
                pass
    return t


def lab_metrics(n=40):
    p = os.path.join(RESEARCH, "metrics.jsonl")
    rows = []
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows[-n:]


def experiments():
    p = os.path.join(ROOT, "data", "research", "experiments.jsonl")
    counts, items = defaultdict(int), []
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            counts[e.get("status", "open")] += 1
            items.append(e)
    return counts, items


# ── tiny inline SVG ───────────────────────────────────────────────────────────
def sparkline(values, w=104, h=26):
    vals = [v for v in (values or []) if v is not None]
    if len(vals) < 2:
        return (f'<svg width="{w}" height="{h}" class="spark">'
                f'<line x1="2" y1="{h/2:.0f}" x2="{w-2}" y2="{h/2:.0f}" '
                f'stroke="#2a2f38" stroke-width="1"/></svg>')
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    pts = " ".join(f"{2 + i/(n-1)*(w-4):.1f},{h-2 - (v-lo)/rng*(h-4):.1f}"
                   for i, v in enumerate(vals))
    col = "#34d399" if vals[-1] >= 0 else "#f87171"
    zero = ""
    if lo < 0 < hi:
        zy = h - 2 - (0 - lo) / rng * (h - 4)
        zero = f'<line x1="2" y1="{zy:.1f}" x2="{w-2}" y2="{zy:.1f}" stroke="#2a2f38" stroke-dasharray="2 2"/>'
    return (f'<svg width="{w}" height="{h}" class="spark">{zero}'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.5"/></svg>')


def equity_curve_svg(values, w=560, h=140):
    vals = [0.0] + [v for v in (values or []) if v is not None]
    if len(vals) < 2:
        return '<div class="muted pad">No forward games yet — curve appears after the first live game.</div>'
    lo, hi = min(vals + [0]), max(vals + [0])
    rng = (hi - lo) or 1
    n = len(vals)
    pl, pr, pt, pb = 44, 8, 10, 18

    def x(i):
        return pl + i / (n - 1) * (w - pl - pr)

    def y(v):
        return pt + (1 - (v - lo) / rng) * (h - pt - pb)

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    col = "#34d399" if vals[-1] >= 0 else "#f87171"
    grid = ""
    for gv in (lo, 0 if lo < 0 < hi else (lo + hi) / 2, hi):
        gy = y(gv)
        grid += (f'<line x1="{pl}" y1="{gy:.1f}" x2="{w-pr}" y2="{gy:.1f}" stroke="#1c2027"/>'
                 f'<text x="4" y="{gy+3:.0f}" fill="#5b6068" font-size="10">{gv:+.0f}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px">{grid}'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8"/></svg>')


def line_chart(values, w=640, h=210):
    """A clear, labeled line chart over runs — y-axis values, dots, end labels."""
    vals = [v for v in (values or []) if v is not None]
    if not vals:
        return '<div class="muted pad">No data yet — the line builds as the daily loop runs.</div>'
    if len(vals) == 1:
        return (f'<div class="pad"><span style="font-size:30px;font-weight:750">{vals[0]:.3f}</span>'
                f'<div class="sub">one reading so far — the trend line appears once the loop has run a few days</div></div>')
    lo, hi = min(vals), max(vals)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    pl, pr, pt, pb = 46, 14, 18, 16
    rng = hi - lo
    n = len(vals)
    fx = lambda i: pl + i / (n - 1) * (w - pl - pr)
    fy = lambda v: pt + (1 - (v - lo) / rng) * (h - pt - pb)
    grid = ""
    for frac in (0, 0.5, 1.0):
        gv = lo + frac * rng
        gy = fy(gv)
        grid += (f'<line x1="{pl}" y1="{gy:.0f}" x2="{w-pr}" y2="{gy:.0f}" stroke="#1c2027"/>'
                 f'<text x="6" y="{gy+4:.0f}" fill="#5b6068" font-size="11">{gv:+.2f}</text>')
    pts = " ".join(f"{fx(i):.1f},{fy(v):.1f}" for i, v in enumerate(vals))
    col = "#34d399" if vals[-1] >= vals[0] else "#f87171"
    dots = ""
    for i, v in enumerate(vals):
        dots += f'<circle cx="{fx(i):.1f}" cy="{fy(v):.1f}" r="3.2" fill="{col}"/>'
        if i in (0, n - 1) or n <= 7:
            dots += (f'<text x="{fx(i):.1f}" y="{fy(v)-9:.0f}" fill="#cbd5e1" font-size="11" '
                     f'text-anchor="middle">{v:+.2f}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px">{grid}'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.2"/>{dots}</svg>')


def _delta(cur, prev):
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if abs(d) < 1e-9:
        return '<span class="flat" style="font-size:13px"> ±0</span>'
    arrow, cls = ("▲", "pos") if d > 0 else ("▼", "neg")
    return f'<span class="{cls}" style="font-size:14px"> {arrow}{abs(d):.2f}</span>'


# ── shared style ──────────────────────────────────────────────────────────────
CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0a0b0d;--panel:#131519;--panel2:#0f1115;--line:#20242c;--tx:#e5e7eb;--mut:#7b818c;--acc:#5b9cff}
body{font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;background:var(--bg);color:var(--tx);max-width:1180px;margin:0 auto;padding:24px}
a{color:var(--acc);text-decoration:none} a:hover{text-decoration:underline}
.muted{color:var(--mut)} .sm{font-size:12px} .pad{padding:10px 2px}
.mono{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
h1{color:var(--acc);font-size:21px} h2{font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:#cbd5e1;margin:26px 0 10px}
.sub{color:var(--mut);font-size:12px}
.summary{display:flex;flex-wrap:wrap;gap:8px 20px;margin:10px 0 4px;padding:12px 16px;background:var(--panel);border:1px solid var(--line);border-radius:11px}
.summary .kv{font-size:13px} .summary b{color:#fff;font-weight:650}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:11px}
.gcard{display:block;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:13px;color:var(--tx)}
.gcard:hover{border-color:var(--acc);text-decoration:none}
.gcard .hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.gcard .teams{font-weight:650} .gcard .scr{font-size:22px;font-weight:750;letter-spacing:-.5px;margin:2px 0}
.pill{font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;border:1px solid var(--line)}
.pill.live{color:#34d399;border-color:#34d39955} .pill.pre{color:#f5b945;border-color:#f5b94555}
.pill.final{color:var(--mut)} .lg{font-size:10px;color:var(--mut);font-weight:700;letter-spacing:.5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--line);padding:7px 9px}
td{padding:9px;border-bottom:1px solid var(--panel2);vertical-align:middle}
tr:hover td{background:#0e1014}
.stage{font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:5px;border:1px solid}
.stage.LIVE{color:#34d399;border-color:#34d39955}.stage.PAPER{color:#5b9cff;border-color:#5b9cff55}
.stage.DEV{color:#f5b945;border-color:#f5b94555}.stage.PAST{color:#6b7280;border-color:#6b728055}
.pos{color:#34d399}.neg{color:#f87171}.flat{color:#8b909a}
.spark{vertical-align:middle}
.nm{font-weight:600} .desc{color:#9aa0ab;font-size:12px;max-width:320px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:16px;margin-bottom:12px}
.back{display:inline-block;color:var(--acc);font-size:12px;border:1px solid var(--line);padding:3px 10px;border-radius:7px;margin-bottom:14px}
.bk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
.foot{color:var(--mut);font-size:11px;margin-top:24px;text-align:center}
.tag{display:inline-block;font-size:11px;color:var(--mut);background:#0e1014;border:1px solid var(--line);border-radius:6px;padding:2px 7px;margin:2px 4px 2px 0}
.progress-card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:16px 18px;color:var(--tx)}
.progress-card:hover{border-color:var(--acc);text-decoration:none}
.prog-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.prog-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:15px 0 12px}
.ptile{background:#0e1014;border:1px solid var(--line);border-radius:9px;padding:13px 15px}
.ptile .pn{font-size:25px;font-weight:750;font-variant-numeric:tabular-nums}
.ptile .pl{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
.prog-explain{line-height:1.65;font-size:12px;color:#9aa0ab;border-top:1px solid var(--panel2);padding-top:11px}
.prog-explain b{color:#cbd5e1;font-weight:600}
.lab-section{margin-bottom:22px} .lab-cap{font-size:12px;color:var(--mut);margin:4px 2px 10px}
"""


def _money(x, dp=2):
    return "—" if x is None else f"{'+' if x >= 0 else ''}{x:.{dp}f}"


def _pcol(x):
    return "pos" if (x or 0) > 0 else ("neg" if (x or 0) < 0 else "flat")


# ── the board (docs/index.html) ───────────────────────────────────────────────
def render_board(state, live, bt, curve):
    funding = state.get("funding", {})
    stage = _key2stage(state)
    inv = data_inventory(bt)

    total_live = sum(a["net"] for a in live.values())
    by_lg = " / ".join(f"{lg} {n}" for lg, n in sorted(inv["by_league"].items())) or "—"
    summ = (f'<div class="summary">'
            f'<span class="kv">params <b>v{strat.params_version()}</b></span>'
            f'<span class="kv">captured <b>{inv["captured"]}</b> games · {by_lg}</span>'
            f'<span class="kv">backtest <b>{inv["backtest"]}</b> games</span>'
            f'<span class="kv">forward paper P&amp;L <b class="{_pcol(total_live)}">{_money(total_live)}</b></span>'
            f'<span class="kv">live-funded <b>{len(state.get("LIVE", []))}</b></span>'
            f'<span class="kv">research spend (mo) <b>${research_spend():.2f}</b></span>'
            f'<span class="kv sub">updated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</span>'
            f'</div>')

    oq = open_questions()
    needs = ""
    if oq:
        items = "".join(f"<li>{q}</li>" for q in oq)
        needs = (f'<div class="panel" style="border-color:#5c4a12">'
                 f'<div style="color:#f5b945;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">⚠ Needs you ({len(oq)})</div>'
                 f'<ul style="line-height:1.7;font-size:13px;margin-left:16px">{items}</ul>'
                 f'<div class="sub" style="margin-top:4px">full details in docs/OPEN_QUESTIONS.md</div></div>')

    rl_rows = ""
    for r in research_log():
        ts = (r.get("ts", "") or "")[:16].replace("T", " ")
        rl_rows += (f'<tr><td class="mono sub" style="white-space:nowrap">{ts}</td>'
                    f'<td><span class="stage PAPER">{r.get("kind","note")}</span></td>'
                    f'<td><b>{r.get("title","")}</b>'
                    f'<div class="desc" style="max-width:640px">{r.get("detail","")}</div></td></tr>')
    rl_html = (f'<table><thead><tr><th>when</th><th>kind</th><th>what</th></tr></thead>'
               f'<tbody>{rl_rows}</tbody></table>' if rl_rows else
               '<div class="muted pad">No autonomous iterations yet — the daily local research loop fills this in.</div>')

    # "Last iteration" — when the most recent research run happened + what it decided
    li_when, li_entries = last_iteration()
    if li_entries:
        latest_ts = li_entries[0]["ts"]
        li_items = "".join(
            f'<li style="margin-bottom:7px"><span class="stage PAPER">{r.get("kind","note")}</span> '
            f'<b>{r.get("title","")}</b>'
            f'<div class="desc" style="max-width:660px">{r.get("detail","")}</div></li>'
            for r in li_entries)
        last_iter_html = (
            f'<div class="sub" style="margin-bottom:8px">ran <b style="color:var(--acc)">{_ago(latest_ts)}</b> '
            f'· {latest_ts[:16].replace("T", " ")} UTC · <b>{len(li_entries)}</b> decision(s) this run</div>'
            f'<ul style="line-height:1.45;font-size:13px;list-style:none;margin:0;padding:0">{li_items}</ul>')
    else:
        last_iter_html = '<div class="muted pad">No research iteration logged yet.</div>'

    # lab progress: a clean, clickable card (the full chart lives on lab.html)
    mets = lab_metrics()
    latest = mets[-1] if mets else {}
    prev = mets[-2] if len(mets) >= 2 else {}
    ecounts, _ = experiments()
    ns = latest.get("north_star")
    ns_txt = "—" if ns is None else f"{ns:+.2f}"
    progress = (
        '<a class="progress-card" href="lab.html">'
        '<div class="prog-head">'
        '<div class="sub">Is the lab tending toward higher / more consistent profit?</div>'
        '<span class="sub" style="color:var(--acc)">open the full trend →</span></div>'
        '<div class="prog-tiles">'
        f'<div class="ptile"><div class="pn">{ns_txt}{_delta(ns, prev.get("north_star"))}</div>'
        '<div class="pl">north-star</div></div>'
        f'<div class="ptile"><div class="pn">{latest.get("forward_bets","—")}'
        ' <span class="sub" style="font-size:13px">/ 100</span></div>'
        '<div class="pl">real games tested</div></div>'
        f'<div class="ptile"><div class="pn">{latest.get("decay","—")}</div>'
        '<div class="pl">backtest → live decay</div></div>'
        f'<div class="ptile"><div class="pn" style="font-size:17px">{latest.get("best_strategy","—")}</div>'
        '<div class="pl">leading strategy</div></div>'
        '</div>'
        '<div class="prog-explain">'
        "<b>North-star</b> — our best strategy's profit per game minus half its worst game; "
        "higher = more money and smaller crashes. &nbsp;&nbsp;"
        "<b>Decay</b> — how much worse it does on real upcoming games than in backtest; "
        "near 0 = the edge is real, big = overfit. &nbsp;&nbsp;"
        "<b>Real games tested</b> — we don't trust any edge until ~100. &nbsp;&nbsp;"
        f'{ecounts.get("validated",0)} experiments validated · {ecounts.get("killed",0)} killed · '
        f'{ecounts.get("open",0)} open.</div>'
        '</a>')

    # live & today games
    cards = []
    for g in recent_games(8):
        cls = g["status"].lower()
        sc = g.get("score") or {}
        scs = (f'{sc.get("away","-")}–{sc.get("home","-")}'
               if sc.get("home") is not None else "vs")
        clk = ""
        if g["status"] in ("LIVE", "PRE") and g.get("period"):
            clk = f'<span class="sm muted">Q{g.get("period")} {g.get("clock","")}</span>'
        top = ""
        if g.get("top"):
            t = g["top"]
            top = (f'<div class="sm">top: <span class="{_pcol(t["pnl"])}">{t["name"]} '
                   f'{_money(t["pnl"])}</span> · {t["n"]} traded</div>')
        elif g["status"] in ("LIVE", "PRE"):
            top = '<div class="sm muted">capturing…</div>'
        cards.append(
            f'<a class="gcard" href="games/{g["id"]}.html">'
            f'<div class="hd"><span class="lg">{g["league"]}</span>'
            f'<span class="pill {cls}">{g["status"]}</span></div>'
            f'<div class="teams">{g["away"]} <span class="muted">@</span> {g["home"]}</div>'
            f'<div class="scr">{scs} {clk}</div>{top}</a>')
    cards_html = "".join(cards) or '<div class="muted pad">No games captured yet.</div>'

    # strategy table
    def srow(key):
        cls = strat.REGISTRY.get(key)
        if not cls:
            return ""
        lab = cls.label
        st = stage.get(key, "—")
        a = live.get(key, {})
        b = bt.get(key, {})
        bt_pg = b.get("per_game")
        bwl = (b.get("wins", 0) + b.get("losses", 0))
        bt_wr = f'{b.get("wins",0)/bwl*100:.0f}%' if bwl else "—"
        bt_cell = (f'<span class="{_pcol(bt_pg)}">{_money(bt_pg)}</span>/g · {bt_wr}'
                   if b else '<span class="muted">—</span>')
        lwl = a.get("w", 0) + a.get("l", 0)
        lv_pg = (a["net"] / a["games"]) if a.get("games") else None
        lv_wr = f'{a["w"]/lwl*100:.0f}%' if lwl else "—"
        lv_cell = (f'<span class="{_pcol(lv_pg)}">{_money(lv_pg)}</span>/g · {lv_wr} '
                   f'<span class="muted sm">({a["games"]}g)</span>' if a.get("games")
                   else '<span class="muted">— (0g)</span>')
        worst = a.get("worst")
        worst_cell = (f'<span class="{_pcol(worst)}">{_money(worst)}</span>'
                      if worst is not None else '<span class="muted">—</span>')
        spark = sparkline(curve.get(key, []))
        wallet = '<span class="muted">—</span>'
        if st == "LIVE" and key in funding:
            bal = funding[key] + a.get("net", 0)
            floor = funding[key] * (1 - FLOOR)
            wcls = "pos" if bal > floor * 1.2 else ("neg" if bal <= floor else "flat")
            wallet = f'<span class="{wcls}">${bal:.0f}/${funding[key]:.0f}</span> <span class="muted sm">floor ${floor:.0f}</span>'
        desc = (cls.description or "")[:96]
        return (f'<tr><td><a class="nm" href="strategy/{key}.html">{lab}</a>'
                f'<div class="desc">{desc}</div></td>'
                f'<td><span class="stage {st}">{st}</span></td>'
                f'<td class="mono">{bt_cell}</td><td class="mono">{lv_cell}</td>'
                f'<td class="mono">{worst_cell}</td><td>{spark}</td><td>{wallet}</td></tr>')

    keys = sorted(strat.REGISTRY,
                  key=lambda k: (STAGE_ORDER.get(stage.get(k, "PAST"), 9),
                                 -((bt.get(k) or {}).get("per_game") or -999)))
    table = "".join(srow(k) for k in keys)

    inv_html = (f'<span class="tag">{inv["backtest"]} backtest games</span>'
                f'<span class="tag">{inv["captured"]} captured games</span>'
                + "".join(f'<span class="tag">{lg}: {n}</span>'
                          for lg, n in sorted(inv["by_league"].items()))
                + f'<span class="tag">{inv["decisions"]} decisions logged</span>')

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>Kalshi Lab — Board</title>
<style>{CSS}</style></head><body>
<h1>🏀 Kalshi Lab</h1>
{summ}
{needs}
<h2>Live &amp; Today <span class="sub">click a game → order flow</span></h2>
<div class="cards">{cards_html}</div>
<h2>Strategies <span class="sub">click a name → full history</span></h2>
<table><thead><tr><th>strategy</th><th>stage</th><th>backtest $/g · win%</th>
<th>live $/g · win%</th><th>worst game</th><th>equity curve</th><th>wallet vs floor</th>
</tr></thead><tbody>{table}</tbody></table>
<h2>Lab progress <span class="sub">is the lab tending toward higher / more consistent profit?</span></h2>
{progress}
<h2>Last iteration <span class="sub">what the most recent research run decided · when it ran</span></h2>
<div class="panel">{last_iter_html}</div>
<h2>Research log <span class="sub">what the quant did — newest first</span></h2>
<div class="panel">{rl_html}</div>
<h2>Data we have to learn from</h2>
<div class="panel">{inv_html}</div>
<div class="foot">paper trading only · the brain re-tunes the Claude-owned model daily ·
backtest = robustness across past games, live = forward-tested ledger</div>
</body></html>"""
    os.makedirs(DOCS, exist_ok=True)
    open(INDEX, "w").write(html)


# ── per-strategy detail (docs/strategy/<key>.html) ────────────────────────────
def render_strategy_detail(key, state, live, bt, curve):
    cls = strat.REGISTRY.get(key)
    if not cls:
        return
    lab = cls.label
    stage = _key2stage(state).get(key, "—")
    a = live.get(key, {})
    b = bt.get(key, {})

    # header stats
    lwl = a.get("w", 0) + a.get("l", 0)
    lv_pg = (a["net"] / a["games"]) if a.get("games") else None
    bwl = b.get("wins", 0) + b.get("losses", 0)
    hdr = []
    hdr.append(("stage", f'<span class="stage {stage}">{stage}</span>'))
    hdr.append(("live games", str(a.get("games", 0))))
    hdr.append(("live $/game", f'<span class="{_pcol(lv_pg)}">{_money(lv_pg)}</span>'))
    hdr.append(("live win%", f'{a["w"]/lwl*100:.0f}%' if lwl else "—"))
    hdr.append(("worst game", f'<span class="{_pcol(a.get("worst"))}">{_money(a.get("worst"))}</span>'))
    hdr.append(("avg trades/g", f'{a["trades"]/a["games"]:.1f}' if a.get("games") else "—"))
    hdr.append(("backtest $/g", f'<span class="{_pcol(b.get("per_game"))}">{_money(b.get("per_game"))}</span>'))
    hdr.append(("backtest win%", f'{b.get("wins",0)/bwl*100:.0f}%' if bwl else "—"))
    stat_html = "".join(
        f'<div class="panel" style="margin:0;padding:11px 14px"><div class="sub">{k}</div>'
        f'<div style="font-size:17px;font-weight:700;margin-top:2px">{v}</div></div>'
        for k, v in hdr)

    # current params + changelog
    params = strat.load_params().get(key, {})
    try:
        pfile = json.load(open(os.path.join(ROOT, "strategy_params.json")))
        changelog = pfile.get("changelog", [])
    except Exception:
        changelog = []
    p_html = "".join(f'<span class="tag">{pk} = {pv}</span>' for pk, pv in params.items()) or "<span class='muted'>code defaults</span>"
    cl_html = "".join(f'<li><b>v{c.get("version")}</b> · {c.get("date")} — {c.get("note","")}</li>'
                      for c in changelog[-6:][::-1])

    # per-game results
    rows = []
    for g in sorted(a.get("pergame", []), key=lambda r: r.get("ts") or "", reverse=True):
        gid = g["gid"]
        away, home = _gid_teams(gid or "")
        rows.append(f'<tr><td class="mono">{(gid or "").split("_")[0]}</td>'
                    f'<td><span class="lg">{analyze.league_of_gid(gid)}</span></td>'
                    f'<td><a href="../games/{gid}.html">{away} @ {home}</a></td>'
                    f'<td class="mono">{g["trades"]}</td>'
                    f'<td class="mono {_pcol(g["net"])}">{_money(g["net"])}</td>'
                    f'<td class="mono">{g["w"]}W/{g["l"]}L</td></tr>')
    games_tbl = ("".join(rows) or
                 '<tr><td colspan="6" class="muted pad">No forward games yet.</td></tr>')

    # condition breakdowns (filtered to this strategy)
    dims = analyze.condition_breakdowns(analyze._all_decisions(lab))

    def dim_table(title, buckets):
        if not buckets:
            return ""
        body = ""
        for bk, st_ in sorted(buckets.items()):
            wr = st_["w"] / st_["n"] * 100 if st_["n"] else 0
            avg = st_["pnl"] / st_["n"] if st_["n"] else 0
            body += (f'<tr><td>{bk}</td><td class="mono">{st_["n"]}</td>'
                     f'<td class="mono">{wr:.0f}%</td>'
                     f'<td class="mono {_pcol(avg)}">{_money(avg)}</td></tr>')
        return (f'<div class="panel"><div class="sub" style="margin-bottom:7px">by {title}</div>'
                f'<table><thead><tr><th>bucket</th><th>trades</th><th>win%</th>'
                f'<th>avg P&amp;L</th></tr></thead><tbody>{body}</tbody></table></div>')

    breakdowns = "".join(dim_table(t.replace("_", " "), dims.get(t, {}))
                         for t in ("edge_at_entry", "quarter", "side", "league"))

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{lab} — Strategy</title><style>{CSS}</style></head><body>
<a class="back" href="../index.html">← Board</a>
<h1>{lab}</h1>
<div class="desc" style="max-width:760px;font-size:13px">{cls.description}</div>
<div class="bk-grid" style="margin-top:14px">{stat_html}</div>
<h2>Current params <span class="sub">params v{strat.params_version()}</span></h2>
<div class="panel">{p_html}</div>
<h2>Equity curve <span class="sub">cumulative forward P&amp;L</span></h2>
<div class="panel">{equity_curve_svg(curve.get(key, []))}</div>
<h2>Games traded</h2>
<div class="panel"><table><thead><tr><th>date</th><th>lg</th><th>game</th>
<th>trades</th><th>P&amp;L</th><th>W/L</th></tr></thead><tbody>{games_tbl}</tbody></table></div>
<h2>How it does by condition</h2>
<div class="bk-grid">{breakdowns or '<div class="muted pad">No captured trades yet.</div>'}</div>
<h2>Params history</h2>
<div class="panel"><ul style="line-height:1.8;font-size:12.5px;padding-left:18px">{cl_html}</ul></div>
<div class="foot">paper trading only</div>
</body></html>"""
    os.makedirs(STRATDIR, exist_ok=True)
    open(os.path.join(STRATDIR, f"{key}.html"), "w").write(html)


# ── lab progress detail (docs/lab.html) ──────────────────────────────────────
def render_progress():
    mets = lab_metrics(60)
    ns_vals = [m.get("north_star") for m in mets if m.get("north_star") is not None]
    latest = mets[-1] if mets else {}
    _, eitems = experiments()

    hist = ""
    for m in mets[-15:][::-1]:
        hist += (f'<tr><td class="mono sub">{(m.get("ts","") or "")[:16].replace("T"," ")}</td>'
                 f'<td class="mono">{m.get("north_star","—")}</td>'
                 f'<td class="mono">{m.get("bt_per_game","—")}</td>'
                 f'<td class="mono">{m.get("fwd_per_game","—")}</td>'
                 f'<td class="mono">{m.get("decay","—")}</td>'
                 f'<td class="mono">{m.get("forward_bets","—")}</td></tr>')
    hist = hist or '<tr><td colspan="6" class="muted pad">no snapshots yet</td></tr>'

    order = {"open": 0, "validated": 1, "killed": 2}
    exp = ""
    for e in sorted(eitems, key=lambda x: order.get(x.get("status"), 3)):
        sc = {"validated": "pos", "killed": "neg", "open": "flat"}.get(e.get("status"), "flat")
        exp += (f'<tr><td><b>{e.get("id")}</b></td><td><span class="{sc}">{e.get("status","?")}</span></td>'
                f'<td>{e.get("mechanism","?")}</td><td class="mono">{e.get("sample_n","?")}</td>'
                f'<td class="desc" style="max-width:520px">{e.get("hypothesis","")}</td></tr>')
    exp = exp or '<tr><td colspan="5" class="muted pad">none yet</td></tr>'

    def card(term, body):
        return (f'<div class="ptile" style="max-width:none"><div class="pl" style="font-size:12px;'
                f'color:#cbd5e1;text-transform:none;letter-spacing:0">{term}</div>'
                f'<div class="sub" style="margin-top:4px;line-height:1.55">{body}</div></div>')

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60"><title>Lab Progress</title>
<style>{CSS}</style></head><body>
<a class="back" href="index.html">← Board</a>
<h1>Lab Progress</h1>
<div class="lab-cap">Is the lab tending toward higher / more consistent profit? The north-star
is the one number to watch — you want the line going up.</div>

<h2>North-star over time</h2>
<div class="panel">{line_chart(ns_vals)}
<div class="lab-cap" style="margin-top:10px"><b>North-star</b> = our best deployable strategy's
<b>profit per game minus half its worst game</b>. It rewards profit and penalizes big crashes, so a
rising line means we're finding edges that are both more profitable and safer. Backtest-based —
treated as provisional until enough real games confirm it.</div></div>

<h2>What the numbers mean</h2>
<div class="prog-tiles">
{card("North-star", "Best strategy's per-game profit minus ½·its worst game. Higher = more money and smaller crashes. The headline.")}
{card("Backtest → live decay", "How much worse the strategy does on real upcoming games vs the backtest. Near 0 = the edge is real; big positive = overfit to the past.")}
{card("Real games tested", "Out-of-sample games the strategy has actually traded. We don't trust any edge until ~100 — everything below that is provisional.")}
{card("Leading strategy", "Which strategy currently has the best risk-adjusted score. This can change as the loop iterates.")}
</div>

<h2>Recent snapshots</h2>
<div class="panel"><table><thead><tr><th>when</th><th>north-star</th><th>bt $/game</th>
<th>live $/game</th><th>decay</th><th>fwd bets</th></tr></thead><tbody>{hist}</tbody></table></div>

<h2>Experiments <span class="sub">what we're testing, and the verdicts</span></h2>
<div class="panel"><table><thead><tr><th>id</th><th>status</th><th>type</th><th>n</th>
<th>hypothesis</th></tr></thead><tbody>{exp}</tbody></table></div>
<div class="foot">paper trading only · the daily loop updates this</div>
</body></html>"""
    os.makedirs(DOCS, exist_ok=True)
    open(os.path.join(DOCS, "lab.html"), "w").write(html)


# ── orchestration ─────────────────────────────────────────────────────────────
def build(quick=False):
    state = load_state()
    live, bt, curve = compute_stats()
    render_board(state, live, bt, curve)
    # render shards EARLY (live games are the time-sensitive part) and guard the rest,
    # so a failure in a detail page can never block the live shards from updating.
    rendered = shards.render_all(changed_only=quick)
    try:
        render_progress()
    except Exception as e:
        print(f"progress render error: {e}")
    for key in strat.REGISTRY:
        try:
            render_strategy_detail(key, state, live, bt, curve)
        except Exception as e:
            print(f"detail {key} render error: {e}")
    return state, len(rendered)


def main():
    a = sys.argv[1:]
    if a and a[0] == "--move" and len(a) >= 3:
        move(a[1], a[2].upper()); return
    if a and a[0] == "--promote" and len(a) >= 3:
        move(a[1], "LIVE", fund=float(a[2])); return
    if a and a[0] == "--retire" and len(a) >= 2:
        move(a[1], "PAST"); return
    quick = "--quick" in a
    state, n_shards = build(quick=quick)
    print(f"Wrote {INDEX} + {len(strat.REGISTRY)} strategy pages + {n_shards} shards"
          f"{' (quick)' if quick else ''}")
    for board in ("LIVE", "PAPER", "DEV", "PAST"):
        if state.get(board):
            print(f"  {board}: {', '.join(state[board])}")


if __name__ == "__main__":
    main()
