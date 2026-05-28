#!/usr/bin/env python3
"""make_charts.py — generate the X thread charts from the REAL lab data + results.
Outputs PNGs to docs/charts/. Dark 'trading terminal' style."""
import glob, gzip, json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager  # noqa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine
OUT = os.path.join(ROOT, "docs", "charts")
os.makedirs(OUT, exist_ok=True)

BG, FG, GRID = "#0d1117", "#e6edf3", "#30363d"
ACC, RED, GREEN, BLUE, YELL = "#f5b945", "#f85149", "#3fb950", "#58a6ff", "#d29922"
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": FG, "axes.labelcolor": FG, "xtick.color": FG, "ytick.color": FG,
    "axes.edgecolor": GRID, "grid.color": GRID, "font.size": 12, "axes.titlesize": 15,
    "axes.titleweight": "bold", "figure.dpi": 130,
})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def chart_winprob_vs_price():
    # find a corpus game with a big swing for visual interest
    best = None
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "backtest", "*NBA*.json.gz")))[:120]:
        try:
            rec = json.load(gzip.open(p, "rt"))
        except Exception:
            continue
        d, g = rec["data"], rec["g"]
        meta = engine.parse_ticker(g["ticker"])
        cs = [c for c in (d.get("candles") or []) if c.get("c") is not None and c.get("ts")]
        wp = d.get("wp_by_id") or {}
        if len(cs) < 40 or len(wp) < 40:
            continue
        rng = max(c["c"] for c in cs) - min(c["c"] for c in cs)
        if rng > 0.55:                      # a real comeback
            best = (rec, meta); break
    if not best:
        return
    rec, meta = best
    d = rec["data"]; yih = meta["yes_is_home"]
    cs = [c for c in d["candles"] if c.get("c") is not None and c.get("ts")]
    t0 = cs[0]["ts"]
    px_t = [(c["ts"] - t0) / 60 for c in cs]; px = [c["c"] * 100 for c in cs]
    wseries = []
    for pl in d["plays"]:
        w = (d["wp_by_id"] or {}).get(pl.get("id"))
        ts = engine._iso_to_unix(pl.get("wallclock"))
        if w is not None and ts is not None:
            wseries.append(((ts - t0) / 60, (w if yih else 1 - w) * 100))
    wseries.sort()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot([x for x, _ in wseries], [y for _, y in wseries], color=BLUE, lw=2.2,
            label="ESPN win probability")
    ax.plot(px_t, px, color=ACC, lw=2.2, label="Kalshi market price")
    ax.set_title(f"ESPN win prob vs the Kalshi price  ({meta['away']} @ {meta['home']})")
    ax.set_xlabel("minutes into the captured window"); ax.set_ylabel("implied chance (%)")
    ax.set_ylim(0, 100); ax.grid(alpha=.3); ax.legend(loc="best", framealpha=.2)
    ax.text(.5, -.18, "they move together all game. the 'gap' you would trade is mostly noise.",
            transform=ax.transAxes, ha="center", color=ACC, fontsize=11)
    save(fig, "01_winprob_vs_price.png")


def chart_calibration():
    import research.edge_discovery as E
    obs = E.observations()
    edges = [i / 10 for i in range(11)]
    def rel(key):
        xs, ys = [], []
        for i in range(10):
            lo, hi = edges[i], edges[i + 1]
            sel = [o for o in obs if lo <= o[key] < hi]
            if sel:
                xs.append(sum(o[key] for o in sel) / len(sel))
                ys.append(sum(o["yes_won"] for o in sel) / len(sel))
        return xs, ys
    mx, my = rel("market"); gx, gy = rel("model")
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    ax.plot([0, 1], [0, 1], color=GRID, ls="--", lw=1.5, label="perfect calibration")
    ax.plot(mx, my, "o-", color=ACC, lw=2.2, ms=7, label="Kalshi price")
    ax.plot(gx, gy, "s-", color=BLUE, lw=2.2, ms=6, label="ESPN win prob")
    ax.set_title("Who is sharper? Kalshi vs ESPN\nBrier 0.1181 vs 0.1181. identical.")
    ax.set_xlabel("predicted chance"); ax.set_ylabel("actual win rate")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.grid(alpha=.3); ax.legend(loc="upper left", framealpha=.2)
    save(fig, "02_calibration.png")


def chart_the_leak():
    names = ["edge_naive\n(junk control)", "conviction", "auto_house", "wp_momentum"]
    leaked = [11.82, 5.22, 2.82, 0.61]; honest = [-10.45, -1.51, -0.56, -6.32]
    x = range(len(names)); w = 0.38
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.bar([i - w / 2 for i in x], leaked, w, color=RED, label="with the look ahead leak")
    ax.bar([i + w / 2 for i in x], honest, w, color=GREEN, label="after the fix (honest)")
    ax.axhline(0, color=FG, lw=1)
    ax.set_xticks(list(x)); ax.set_xticklabels(names)
    ax.set_ylabel("backtest profit per game ($)")
    ax.set_title("The leak that almost fooled us\na JUNK control showed +$11.82/game until we fixed the timing")
    ax.grid(axis="y", alpha=.3); ax.legend(framealpha=.2)
    for i, v in enumerate(leaked):
        ax.text(i - w / 2, v + .3, f"+{v:.1f}", ha="center", color=RED, fontsize=10)
    for i, v in enumerate(honest):
        ax.text(i + w / 2, v - .9, f"{v:.1f}", ha="center", color=GREEN, fontsize=10)
    save(fig, "03_the_leak.png")


def chart_flow():
    horizons = ["30s", "60s", "120s"]
    gross = [0.05, 0.02, 0.03]            # cents, FLOW_SCAN (centered on zero = noise)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.axhspan(-0.5, 0.5, color=GRID, alpha=.4, label="noise band")
    ax.bar(horizons, gross, color=BLUE, width=.5)
    ax.axhline(0, color=FG, lw=1)
    ax.set_ylim(-4, 4); ax.set_ylabel("gross forward return (cents)")
    ax.set_title("Does order flow predict the next move?\nNo. the return is noise at every horizon.")
    ax.grid(axis="y", alpha=.3); ax.legend(framealpha=.2)
    ax.text(.5, -.16, "net of the round trip cost it is about negative 3 cents. the market eats flow instantly.",
            transform=ax.transAxes, ha="center", color=BLUE, fontsize=10)
    save(fig, "04_flow.png")


def chart_cross_venue():
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["mean gap", "median gap", "max gap (294 games)", "fee hurdle to beat"]
    vals = [1.2, 1.1, 4.0, 3.5]; cols = [ACC, ACC, ACC, RED]
    ax.barh(labels, vals, color=cols)
    for i, v in enumerate(vals):
        ax.text(v + .1, i, f"{v:.1f}c", va="center", color=FG)
    ax.set_xlabel("cents"); ax.set_xlim(0, 5)
    ax.set_title("Kalshi vs the sharp sportsbook line (DraftKings)\nthey never disagree enough to arb")
    ax.grid(axis="x", alpha=.3)
    save(fig, "05_cross_venue.png")


def chart_market_making():
    fee_pct = [0, 25, 50, 100]; net = [0.35, 0.07, -0.22, -0.78]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(fee_pct, net, "o-", color=ACC, lw=2.5, ms=9)
    ax.axhline(0, color=FG, lw=1.2)
    ax.axvline(25, color=GREEN, ls="--", lw=1.8)
    ax.text(27, 0.22, "Kalshi's real maker fee\n(25% of taker) -> +0.07c", color=GREEN, fontsize=10)
    ax.fill_between(fee_pct, net, 0, where=[n > 0 for n in net], color=GREEN, alpha=.15)
    ax.fill_between(fee_pct, net, 0, where=[n <= 0 for n in net], color=RED, alpha=.15)
    ax.set_xlabel("maker fee (as % of the taker fee)"); ax.set_ylabel("net edge per contract (cents)")
    ax.set_title("Market making: a real edge, but fee gated\ngross +0.35c, net just +0.07c after the fee")
    ax.grid(alpha=.3)
    save(fig, "06_market_making.png")


def chart_overview():
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(["NBA", "WNBA"], [246, 57], color=[ACC, BLUE])
    ax.text(246 - 6, 0, "246", va="center", ha="right", color=BG, fontweight="bold")
    ax.text(57 + 4, 1, "57", va="center", color=FG)
    ax.set_xlabel("settled games captured")
    ax.set_title("The data moat: 303 games\neach with price candles + play by play + win prob + order flow + result")
    ax.grid(axis="x", alpha=.3)
    save(fig, "07_overview.png")


if __name__ == "__main__":
    chart_overview()
    chart_winprob_vs_price()
    chart_calibration()
    chart_the_leak()
    chart_flow()
    chart_cross_venue()
    chart_market_making()
    print("done ->", OUT)
