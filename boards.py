#!/usr/bin/env python3
"""
boards.py — the founder's source of truth for what's deployed and how it's doing.

Maintains board state in `boards.json` (which strategy sits on DEV / PAPER / LIVE
/ PAST) and renders `boards.html`: each strategy with its one-liner, paper vs live
stats (from the performance ledger), version, and (live) wallet-vs-floor health.
Also lists today's captured games linking to their per-game dashboards.

    python3 boards.py                 # rebuild boards.html (+ print a text summary)
    python3 boards.py --move conviction LIVE     # move a strategy between boards
    python3 boards.py --promote conviction 100   # PAPER→LIVE, fund $100 (founder action)
    python3 boards.py --retire model_revert      # → PAST
"""
import glob, json, os, sys
from collections import defaultdict
from datetime import datetime, timezone

import strategies as strat

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "boards.json")
GAMES = os.path.join(ROOT, "data", "games")
LEDGER = os.path.join(ROOT, "data", "results", "strategy_history.jsonl")
OUT = os.path.join(ROOT, "boards.html")
FLOOR = 0.50      # halt at −50% of a live allocation


# ── board state ───────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    # default: every registered strategy is paper-testing; nothing live yet
    return {"DEV": [], "PAPER": list(strat.REGISTRY), "LIVE": [], "PAST": [],
            "funding": {}}      # funding: strategy -> live budget $


def save_state(s):
    json.dump(s, open(STATE, "w"), indent=2)


def move(strategy, board, fund=None):
    s = load_state()
    for b in ("DEV", "PAPER", "LIVE", "PAST"):
        if strategy in s[b]:
            s[b].remove(strategy)
    s.setdefault(board, []).append(strategy)
    if fund is not None:
        s.setdefault("funding", {})[strategy] = fund
    save_state(s)
    print(f"{strategy} → {board}" + (f" (funded ${fund})" if fund is not None else ""))


# ── stats from the ledger ───────────────────────────────────────────────────
def _ledger():
    return [json.loads(l) for l in open(LEDGER)] if os.path.exists(LEDGER) else []


def strategy_stats():
    """Per-strategy: live (forward) record + latest backtest snapshot, keyed by
    strategy label AND key (ledger uses label, boards use key)."""
    live = defaultdict(lambda: {"games": 0, "net": 0.0, "w": 0, "l": 0})
    bt = {}
    for r in _ledger():
        key = r.get("key") or r.get("strategy")
        if r.get("source") == "live":
            a = live[key]; a["games"] += 1; a["net"] += r.get("net_pnl") or 0
            a["w"] += r.get("wins") or 0; a["l"] += r.get("losses") or 0
        elif r.get("source") == "backtest":
            bt[key] = r
    return live, bt


def todays_games():
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = []
    for d in sorted(glob.glob(os.path.join(GAMES, f"{today}_*"))):
        gid = os.path.basename(d)
        meta = {}
        mp = os.path.join(d, "meta.json")
        if os.path.exists(mp):
            meta = json.load(open(mp))
        out.append({"id": gid, "league": gid.split("_")[1] if "_" in gid else "?",
                    "final": meta.get("final_score")})
    return out


# ── render ────────────────────────────────────────────────────────────────────
def _desc(key):
    return getattr(strat.REGISTRY.get(key), "description", "")[:80] if key in strat.REGISTRY else ""


def render():
    s = load_state()
    live, bt = strategy_stats()
    funding = s.get("funding", {})

    def rows(board):
        out = []
        for key in s.get(board, []):
            lab = strat.REGISTRY[key].label if key in strat.REGISTRY else key
            lv, b = live.get(key, {}), bt.get(key, {})
            paper = f"{(b.get('per_game') or 0):+.2f}/g · {b.get('wins',0)}/{b.get('losses',0)}" if b else "—"
            livestr = (f"{lv['net']:+.2f} over {lv['games']}g" if lv.get("games") else "—")
            wallet = ""
            if board == "LIVE" and key in funding:
                bal = funding[key] + lv.get("net", 0)
                floor = funding[key] * (1 - FLOOR)
                col = "#34d399" if bal > floor * 1.2 else ("#f87171" if bal <= floor else "#f5b945")
                wallet = f'<span style="color:{col}">${bal:.0f}/${funding[key]:.0f} (floor ${floor:.0f})</span>'
            out.append(f"<tr><td><b>{key}</b></td><td class=d>{_desc(key)}</td>"
                       f"<td class=m>{paper}</td><td class=m>{livestr}</td><td>{wallet}</td></tr>")
        return "".join(out) or '<tr><td colspan=5 class=e>—</td></tr>'

    games = todays_games()
    slate = "".join(
        f'<li>[{g["league"]}] <a href="dashboards/{g["id"]}.html">{g["id"]}</a>'
        f'{" — FINAL "+str(g["final"]) if g.get("final") else ""}</li>' for g in games
    ) or "<li class=e>no games captured today yet</li>"

    def board_html(name, sub):
        return (f'<h2>{name} <span class=sub>{sub}</span></h2>'
                f'<table><thead><tr><th>strategy</th><th>what it does</th>'
                f'<th>paper ($/game · W/L)</th><th>live</th><th>wallet vs floor</th>'
                f'</tr></thead><tbody>{rows(name)}</tbody></table>')

    html = f"""<!DOCTYPE html><html><head><meta charset=UTF-8>
<meta http-equiv=refresh content=30><title>Lab Boards</title><style>
body{{font:14px -apple-system,Segoe UI,sans-serif;background:#0a0b0d;color:#e5e7eb;max-width:1100px;margin:0 auto;padding:22px}}
h1{{color:#5b9cff}} h2{{font-size:14px;text-transform:uppercase;letter-spacing:.5px;color:#cbd5e1;margin-top:22px}}
.sub{{color:#7b818c;font-size:11px;text-transform:none}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
th{{text-align:left;color:#7b818c;font-size:10px;text-transform:uppercase;border-bottom:1px solid #20242c;padding:6px 8px}}
td{{padding:7px 8px;border-bottom:1px solid #131519}} .d{{color:#9aa0ab;font-size:12px}}
.m{{font-variant-numeric:tabular-nums}} .e{{color:#475569;font-style:italic}}
a{{color:#5b9cff}} ul{{line-height:1.8}} .foot{{color:#7b818c;font-size:11px;margin-top:20px}}
</style></head><body>
<h1>🏀 Kalshi Lab — Boards</h1>
<div class=sub>params v{strat.params_version()} · generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
{board_html('LIVE', 'real money — founder-gated')}
{board_html('PAPER', 'paper testing — auto')}
{board_html('DEV', 'ideas / not yet running')}
{board_html('PAST', 'retired')}
<h2>Today's slate <span class=sub>click a game for its live shard</span></h2>
<ul>{slate}</ul>
<div class=foot>paper = backtest snapshot; live = forward-tested ledger. Boards are the source of truth.</div>
</body></html>"""
    open(OUT, "w").write(html)
    return s, live, bt


def main():
    a = sys.argv[1:]
    if a and a[0] == "--move" and len(a) >= 3:
        move(a[1], a[2].upper()); return
    if a and a[0] == "--promote" and len(a) >= 3:
        move(a[1], "LIVE", fund=float(a[2])); return
    if a and a[0] == "--retire" and len(a) >= 2:
        move(a[1], "PAST"); return
    s, live, bt = render()
    print(f"Wrote {OUT}")
    for board in ("LIVE", "PAPER", "DEV", "PAST"):
        if s.get(board):
            print(f"  {board}: {', '.join(s[board])}")


if __name__ == "__main__":
    main()
