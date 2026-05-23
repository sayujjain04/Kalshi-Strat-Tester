#!/usr/bin/env python3
"""
dashboard.py
─────────────
Renders the live view as a single self-contained, auto-refreshing HTML page.
Minimalist dark "trading terminal" look: lots of whitespace, restrained palette,
green/red reserved for money and trade sides.

The engine assembles a plain-dict view-model (`vm`) and calls write(path, vm).
Everything here is pure formatting — no network, no state.
"""
from datetime import datetime, timezone


# ── formatters ──────────────────────────────────────────────────────────────
def pct(x):
    return "—" if x is None else f"{x*100:.0f}%"

def cents(x):
    return "—" if x is None else f"{x*100:.0f}¢"

def money(x, sign=True):
    if x is None:
        return "—"
    s = "+" if (x >= 0 and sign) else ""
    return f"{s}${x:,.2f}"

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ── candle + probability chart (shared 0–100% y-axis) ────────────────────────
def chart_svg(candles, model_series, height=220):
    if not candles:
        return ('<div class="muted pad">No price history yet — '
                'candles appear once the market is trading.</div>')
    W, H = 1000, height
    pad_l, pad_r, pad_b, pad_t = 38, 8, 18, 10
    lows = [c["l"] for c in candles if c["l"] is not None]
    highs = [c["h"] for c in candles if c["h"] is not None]
    vals = lows + highs + [m for m in (model_series or []) if m is not None]
    if not vals:
        return '<div class="muted pad">No price history yet.</div>'
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or 0.04
    lo, hi = max(0, lo - pad), min(1, hi + pad)
    rng = (hi - lo) or 1

    def y(v):
        return pad_t + (1 - (v - lo) / rng) * (H - pad_t - pad_b)

    n = len(candles)
    plot_w = W - pad_l - pad_r
    step = plot_w / max(n, 1)
    bw = max(1.5, min(10, step * 0.6))

    bars = []
    for i, c in enumerate(candles):
        if c["c"] is None or c["o"] is None:
            continue
        cx = pad_l + i * step + step / 2
        up = c["c"] >= c["o"]
        col = "#34d399" if up else "#f87171"
        if c["h"] is not None and c["l"] is not None:
            bars.append(f'<line x1="{cx:.1f}" y1="{y(c["h"]):.1f}" x2="{cx:.1f}" '
                        f'y2="{y(c["l"]):.1f}" stroke="{col}" stroke-width="1"/>')
        yo, yc = y(c["o"]), y(c["c"])
        top, bh = min(yo, yc), max(1.2, abs(yc - yo))
        bars.append(f'<rect x="{cx-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                    f'height="{bh:.1f}" fill="{col}" rx="0.5"/>')

    # model win-probability line, spread across the same width
    model_line = ""
    ms = [m for m in (model_series or []) if m is not None]
    if len(ms) >= 2:
        pts = " ".join(f"{pad_l + i/(len(ms)-1)*plot_w:.1f},{y(v):.1f}"
                       for i, v in enumerate(ms))
        model_line = (f'<polyline points="{pts}" fill="none" stroke="#5b9cff" '
                      f'stroke-width="1.6" stroke-dasharray="4 3" opacity="0.9"/>')

    # y gridlines at quartiles of the visible range
    grid = ""
    for frac in (0, 0.5, 1.0):
        v = lo + frac * rng
        gy = y(v)
        grid += (f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{W-pad_r}" y2="{gy:.1f}" '
                 f'stroke="#1c2027" stroke-width="1"/>'
                 f'<text x="4" y="{gy+3:.1f}" fill="#5b6068" font-size="10">'
                 f'{v*100:.0f}%</text>')
    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
            f'style="width:100%;height:{height}px">{grid}{"".join(bars)}{model_line}</svg>')


# ── small components ──────────────────────────────────────────────────────────
def prob_bar(implied, model):
    """Two stacked bars comparing market-implied vs model probability for YES."""
    def row(label, v, color):
        w = (v or 0) * 100
        return (f'<div class="pb-row"><span class="pb-lab">{label}</span>'
                f'<div class="pb-track"><div class="pb-fill" style="width:{w:.0f}%;'
                f'background:{color}"></div></div>'
                f'<span class="pb-val">{pct(v)}</span></div>')
    return (row("Market", implied, "#5b9cff") +
            row("Model", model, "#a78bfa"))


def result_badge(r):
    c = {"WIN": "#34d399", "LOSS": "#f87171", "FLAT": "#8b909a", "OPEN": "#f5b945"}.get(r, "#8b909a")
    return f'<span class="badge" style="color:{c};border-color:{c}33">{r}</span>'


def trade_row(t):
    entry = cents(t.entry_price)
    exit_ = cents(t.exit_price) if t.exit_price is not None else "·"
    pnl = money(t.pnl) if t.pnl is not None else "—"
    pcol = "#34d399" if (t.pnl or 0) > 0 else ("#f87171" if (t.pnl or 0) < 0 else "#8b909a")
    reason = _esc(t.entry_reason)
    if t.exit_reason:
        reason += f' <span class="muted">→ exit: {_esc(t.exit_reason)}</span>'
    return (f'<tr><td class="mono">{t.entry_clock or t.entry_time}</td>'
            f'<td>{_esc(t.strategy)}</td>'
            f'<td><span class="side side-{t.side}">{t.side.upper()}</span></td>'
            f'<td class="mono">{entry}→{exit_}</td>'
            f'<td class="mono" style="color:{pcol}">{pnl}</td>'
            f'<td>{result_badge(t.result)}</td>'
            f'<td class="reason">{reason}</td></tr>')


def strat_card(s):
    eq = s["equity"]
    base = 100.0
    pnl = eq - base
    pcol = "#34d399" if pnl > 0 else ("#f87171" if pnl < 0 else "#8b909a")
    wr = pct(s["win_rate"]) if s["win_rate"] is not None else "—"
    open_html = '<div class="muted sm">Flat — waiting for signal</div>'
    if s["open"]:
        t = s["open"]
        open_html = (f'<div class="sm"><span class="side side-{t.side}">{t.side.upper()}</span> '
                     f'{t.qty:g} @ {cents(t.entry_price)} '
                     f'<span class="muted">· {_esc(t.entry_reason)}</span></div>')
    return (f'<div class="scard"><div class="scard-top">'
            f'<span class="scard-name">{_esc(s["strategy"])}</span>'
            f'<span class="scard-eq" style="color:{pcol}">${eq:,.2f} '
            f'<small>({money(pnl)})</small></span></div>'
            f'<div class="scard-sub">{s["n_trades"]} trades · {s["wins"]}W/{s["losses"]}L · win {wr}</div>'
            f'{open_html}</div>')


# ── page ──────────────────────────────────────────────────────────────────────
def build_html(vm):
    g = vm["game"]; m = vm["market"]
    away, home = g.get("away", "AWAY"), g.get("home", "HOME")
    yes_team = vm.get("yes_team", "")
    status = {"pre": "PRE-GAME", "in": "LIVE", "post": "FINAL"}.get(g.get("status"), "—")
    refresh = vm.get("refresh", 5)

    implied, model = vm.get("implied_p_yes"), vm.get("model_p_yes")
    edge = (model - implied) if (model is not None and implied is not None) else None
    edge_col = "#34d399" if (edge or 0) > 0 else ("#f87171" if (edge or 0) < 0 else "#8b909a")
    edge_txt = "—" if edge is None else f"{'+' if edge>=0 else ''}{edge*100:.0f}¢ {'YES cheap' if edge>0 else 'YES rich'}"

    ws_dot = "ok" if m.get("connected") else "off"
    espn_dot = "ok" if g.get("connected") else "off"
    mode = vm.get("mode", "LIVE")

    # run indicator
    run_html = ""
    if g.get("run_team") and (g.get("run_size") or 0) >= 4:
        rt = away if g["run_team"] == "away" else home
        run_html = f'<div class="run">🔥 {rt} on a {g["run_size"]}-0 run</div>'

    # order flow
    imb = m.get("imbalance") or 0.0
    imb_pos = (imb + 1) / 2 * 100
    flow = m.get("trade_flow") or 0.0
    tape = ""
    for t in reversed(m.get("trades", [])[-10:]):
        side = t.get("taker_side", "")
        col = "#34d399" if side == "yes" else "#f87171"
        tape += (f'<div class="tape-row"><span style="color:{col}">{(side or "?").upper()}</span>'
                 f'<span class="mono">{cents(t.get("price"))}</span>'
                 f'<span class="muted mono">×{t.get("count",0):g}</span></div>')
    if not tape:
        tape = '<div class="muted sm pad">No trades yet (live only).</div>'

    # plays
    plays_html = ""
    for p in vm.get("plays", [])[-12:][::-1]:
        plays_html += (f'<div class="play"><span class="mono muted">Q{p.get("period","?")} '
                       f'{p.get("clock","")}</span> {_esc(p.get("text",""))}</div>')
    if not plays_html:
        plays_html = '<div class="muted sm pad">Waiting for play-by-play…</div>'

    # leaderboard + journal
    cards = "".join(strat_card(s) for s in vm.get("leaderboard", []))
    journal = "".join(trade_row(t) for t in vm.get("journal", [])[:40])
    if not journal:
        journal = ('<tr><td colspan="7" class="muted pad">No trades yet — '
                   'strategies are watching the market.</td></tr>')

    total_eq = sum(s["equity"] for s in vm.get("leaderboard", [])) or 0
    n_strat = len(vm.get("leaderboard", [])) or 1
    total_base = 100.0 * n_strat
    total_pnl = total_eq - total_base
    tcol = "#34d399" if total_pnl > 0 else ("#f87171" if total_pnl < 0 else "#e5e7eb")

    chart = chart_svg(vm.get("candles", []), vm.get("model_series", []))

    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>{_esc(away)} @ {_esc(home)} — Live Tracker</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#0a0b0d;--panel:#131519;--panel2:#0f1115;--line:#20242c;--tx:#e5e7eb;--mut:#7b818c;--acc:#5b9cff}}
body{{font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;
background:var(--bg);color:var(--tx);padding:22px;max-width:1240px;margin:0 auto}}
.muted{{color:var(--mut)}} .sm{{font-size:12px}} .pad{{padding:10px 2px}}
.mono{{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
.top{{display:flex;align-items:center;gap:14px;margin-bottom:18px;flex-wrap:wrap}}
.match{{font-size:18px;font-weight:650;letter-spacing:.2px}}
.yes-tag{{font-size:11px;color:var(--mut)}}
.pill{{font-size:11px;font-weight:600;padding:3px 9px;border-radius:99px;border:1px solid var(--line)}}
.pill.live{{color:#34d399;border-color:#34d39933}} .pill.pre{{color:#f5b945;border-color:#f5b94533}}
.pill.final{{color:var(--mut)}} .pill.mode{{color:var(--acc);border-color:#5b9cff33}}
.dot{{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px}}
.dot.ok{{background:#34d399}} .dot.off{{background:#f87171}}
.grid{{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:12px;margin-bottom:12px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px}}
.lab{{font-size:10.5px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);margin-bottom:9px}}
.score{{display:flex;align-items:center;justify-content:space-between}}
.score .t{{text-align:center;flex:1}} .score .n{{font-size:12px;color:var(--mut)}}
.score .p{{font-size:34px;font-weight:750;letter-spacing:-1px}}
.score .mid{{font-size:12px;color:var(--mut);text-align:center;min-width:64px}}
.pb-row{{display:flex;align-items:center;gap:9px;margin:7px 0}}
.pb-lab{{width:46px;font-size:11px;color:var(--mut)}}
.pb-track{{flex:1;height:8px;background:#1b1f27;border-radius:5px;overflow:hidden}}
.pb-fill{{height:100%;border-radius:5px}}
.pb-val{{width:38px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums}}
.edge{{margin-top:11px;font-size:13px;font-weight:650}}
.big{{font-size:30px;font-weight:750;letter-spacing:-1px}}
.cols{{display:grid;grid-template-columns:1.55fr 1fr;gap:12px;margin-bottom:12px}}
.run{{background:#211a06;border:1px solid #5c4a12;color:#f5b945;border-radius:9px;
padding:9px 13px;font-weight:650;font-size:13px;margin-bottom:12px}}
.flow{{display:flex;gap:18px;align-items:center;margin-bottom:11px}}
.imb-track{{flex:1;height:9px;background:#1b1f27;border-radius:5px;position:relative;overflow:hidden}}
.imb-fill{{position:absolute;top:0;bottom:0;background:linear-gradient(90deg,#f87171,#5b9cff)}}
.imb-mark{{position:absolute;top:-3px;width:2px;height:15px;background:#fff}}
.tape-row,.play{{display:flex;gap:10px;font-size:12px;padding:3px 0;border-bottom:1px solid var(--panel2)}}
.tape-row span:first-child{{width:34px;font-weight:600}}
.play{{display:block;border-bottom:1px solid var(--panel2);padding:5px 0}}
.scards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin-bottom:12px}}
.scard{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px}}
.scard-top{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px}}
.scard-name{{font-weight:650}} .scard-eq{{font-weight:700;font-variant-numeric:tabular-nums}}
.scard-eq small{{font-weight:500;opacity:.8}}
.scard-sub{{font-size:11px;color:var(--mut);margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th{{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut);
padding:7px 9px;border-bottom:1px solid var(--line)}}
td{{padding:8px 9px;border-bottom:1px solid var(--panel2);vertical-align:top}}
.side{{font-weight:700;font-size:11px}} .side-yes{{color:#34d399}} .side-no{{color:#f87171}}
.badge{{font-size:10px;font-weight:700;padding:1px 7px;border-radius:99px;border:1px solid}}
.reason{{color:#c3c8d2;max-width:380px}}
h2{{font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);margin:6px 2px 9px}}
.foot{{color:var(--mut);font-size:11px;margin-top:16px;text-align:center}}
</style></head><body>

<div class="top">
  <span class="match">{_esc(away)} <span class="muted">@</span> {_esc(home)}</span>
  <span class="pill {status.lower().split('-')[0]}">{status}</span>
  <span class="pill mode">{_esc(mode)}</span>
  <span class="yes-tag">YES = {_esc(yes_team)} wins</span>
  <span class="sm muted" style="margin-left:auto">
    <span class="dot {ws_dot}"></span>Kalshi&nbsp;&nbsp;<span class="dot {espn_dot}"></span>ESPN
    &nbsp;·&nbsp;updates {refresh}s</span>
</div>

<div class="grid">
  <div class="panel">
    <div class="lab">Scoreboard</div>
    <div class="score">
      <div class="t"><div class="n">{_esc(away)}</div><div class="p">{g["score"]["away"]}</div></div>
      <div class="mid">Q{g.get("period","–")}<br>{_esc(g.get("clock",""))}</div>
      <div class="t"><div class="n">{_esc(home)}</div><div class="p">{g["score"]["home"]}</div></div>
    </div>
  </div>
  <div class="panel">
    <div class="lab">Win Probability — {_esc(yes_team)}</div>
    {prob_bar(implied, model)}
    <div class="edge" style="color:{edge_col}">Edge: {edge_txt}</div>
  </div>
  <div class="panel">
    <div class="lab">Paper P&amp;L (all strategies)</div>
    <div class="big" style="color:{tcol}">{money(total_pnl)}</div>
    <div class="sm muted">${total_eq:,.2f} of ${total_base:,.0f} · {n_strat} strateg{'y' if n_strat==1 else 'ies'} × $100</div>
  </div>
</div>

{run_html}

<div class="cols">
  <div class="panel">
    <div class="lab">Kalshi Price (candles) · Model win-prob (— — line)</div>
    {chart}
    <div class="flow" style="margin-top:14px">
      <span class="sm muted">Book</span>
      <div class="imb-track"><div class="imb-fill" style="width:100%"></div>
        <div class="imb-mark" style="left:calc({imb_pos:.0f}% - 1px)"></div></div>
      <span class="sm mono">{imb:+.0%}</span>
    </div>
    <div class="sm muted">Last {cents(m.get('last_price'))} · spread {cents(m.get('spread'))} ·
      vol {(m.get('volume') or 0):,.0f} · flow {flow:+.0f}</div>
  </div>
  <div class="panel">
    <div class="lab">Order Flow — recent trades</div>
    {tape}
  </div>
</div>

<h2>Strategies</h2>
<div class="scards">{cards or '<div class="muted pad">No strategies loaded.</div>'}</div>

<div class="cols">
  <div class="panel">
    <div class="lab">Trade Journal — what fired, why, and the outcome</div>
    <table><thead><tr><th>Clock</th><th>Strategy</th><th>Side</th><th>Entry→Exit</th>
      <th>P&amp;L</th><th>Result</th><th>Reason</th></tr></thead>
      <tbody>{journal}</tbody></table>
  </div>
  <div class="panel">
    <div class="lab">Play-by-Play</div>
    {plays_html}
  </div>
</div>

<div class="foot">Generated {vm.get('generated','')} · paper trading only, no real orders placed</div>
</body></html>"""


def write(path, vm):
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_html(vm))
