#!/usr/bin/env python3
"""
cross_venue.py — EXP-008 done right: Kalshi vs the sharp sportsbook line (DraftKings,
free via ESPN `pickcenter`). The earlier 34-game look was too small + opening-vs-closing
mismatched; this does ALL corpus games, one independent pre-game bet per game, and reports
EXPECTANCY / win-rate / avg-win-vs-loss (a small but real +EV is scalable by unit size —
not just pass/fail vs a high hurdle), with an OOS time-split and a tail check.

Two questions:
  1. Is the de-vig DK closing line BETTER calibrated than Kalshi's tip price? (Brier)
  2. When they DIVERGE, does betting Kalshi toward the book (hold to settlement, net of the
     fee + the spread you cross) make money — consistently, with a survivable tail?

    python3 research/cross_venue.py
"""
import glob, gzip, json, os, sys, time, statistics as st
from collections import defaultdict

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine                                            # noqa: E402

CORPUS = os.path.join(ROOT, "data", "backtest")
OUT = os.path.join(ROOT, "docs", "CROSS_VENUE.md")
UA = {"User-Agent": "r/2.0"}
FEE_K = 0.07
SPORT = {"NBA": "basketball/nba", "WNBA": "basketball/wnba"}


def ml_to_p(ml):
    ml = float(ml)
    return (100 / (ml + 100)) if ml > 0 else ((-ml) / ((-ml) + 100))


def book_devig_yes(espn_id, sport, yes_is_home):
    """De-vigged DraftKings win prob for the YES side, from ESPN pickcenter. None if absent."""
    try:
        sm = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/{sport}/summary",
                          params={"event": espn_id}, headers=UA, timeout=12).json()
    except Exception:
        return None
    for dk in (sm.get("pickcenter") or []):
        mlh = dk.get("homeTeamOdds", {}).get("moneyLine")
        mla = dk.get("awayTeamOdds", {}).get("moneyLine")
        if mlh is None or mla is None:
            continue
        ph, pa = ml_to_p(mlh), ml_to_p(mla)
        if ph + pa <= 0:
            continue
        fair_home = ph / (ph + pa)
        return fair_home if yes_is_home else 1 - fair_home
    return None


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps) if ps else None


def collect():
    rows = []   # dict per game: date, kalshi_yes, book_yes, fill_yes_ask, fill_no_ask, yes_won
    for p in sorted(glob.glob(os.path.join(CORPUS, "*.json.gz"))):
        try:
            rec = json.load(gzip.open(p, "rt", encoding="utf-8"))
        except Exception:
            continue
        g, d = rec.get("g", {}), rec.get("data", {})
        if d.get("kalshi_result") not in ("yes", "no"):
            continue
        meta = engine.parse_ticker(g.get("ticker", ""))
        sport = SPORT.get(g.get("league"))
        if not meta or not sport or not g.get("espn_id"):
            continue
        cs = [c for c in (d.get("candles") or []) if c.get("c") is not None]
        if not cs:
            continue
        tip = cs[0]                                   # price at/near tip-off = Kalshi "closing"
        book = book_devig_yes(g["espn_id"], sport, meta["yes_is_home"])
        if book is None:
            continue
        yb = tip.get("yb") or max(0.0, tip["c"] - 0.005)
        ya = tip.get("ya") or min(1.0, tip["c"] + 0.005)
        rows.append({"date": g.get("date", ""), "kalshi": tip["c"], "book": book,
                     "ya": ya, "yb": yb, "yes_won": 1 if d["kalshi_result"] == "yes" else 0})
        time.sleep(0.05)
    return rows


def _hurdle(p):
    return FEE_K * p * (1 - p)


def expectancy(rows, thresh):
    """Bet Kalshi toward the book when |book−kalshi| ≥ thresh; hold to settlement, fill at
    the ask we cross, net of entry fee. Returns expectancy + win/loss profile (per game)."""
    pnls = []
    for r in rows:
        gap = r["book"] - r["kalshi"]
        if abs(gap) < thresh:
            continue
        if gap > 0:                                   # book says YES underpriced on Kalshi
            fill = r["ya"]; pnl = (r["yes_won"] - fill) - _hurdle(fill)
        else:
            fill = 1 - r["yb"]; pnl = ((1 - r["yes_won"]) - fill) - _hurdle(fill)
        pnls.append(pnl)
    if not pnls:
        return None
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    return {"n": len(pnls), "exp": st.mean(pnls), "winrate": len(wins) / len(pnls),
            "avg_win": st.mean(wins) if wins else 0.0,
            "avg_loss": st.mean(losses) if losses else 0.0,
            "worst": min(pnls), "total": sum(pnls)}


def main():
    print("collecting DK lines for corpus games (free via ESPN)…", flush=True)
    rows = collect()
    rows.sort(key=lambda r: r["date"])
    n = len(rows)
    if n < 20:
        print(f"only {n} games with DK lines — insufficient"); return
    kp = [r["kalshi"] for r in rows]; bp = [r["book"] for r in rows]; ys = [r["yes_won"] for r in rows]
    bk, bb = brier(kp, ys), brier(bp, ys)
    divs = [abs(r["book"] - r["kalshi"]) for r in rows]

    split = rows[: int(n * 0.6)]; hold = rows[int(n * 0.6):]

    L = ["# CROSS-VENUE — EXP-008 done right (Kalshi vs de-vig DraftKings)",
         f"\n_`research/cross_venue.py`. {n} games with a DK line (free via ESPN pickcenter). "
         "One independent pre-game bet per game (tip-off price vs DK closing line). Reported "
         "as expectancy / win-rate / win-vs-loss size — a small REAL +EV is scalable._\n",
         "## Is either side sharper?",
         f"- **Brier: Kalshi {bk:.4f} · de-vig DK {bb:.4f}** → "
         f"{'DK sharper' if bb < bk else 'Kalshi sharper'} by {abs(bk-bb):.4f}",
         f"- |Kalshi − DK| divergence: mean {st.mean(divs)*100:.1f}¢ · median "
         f"{st.median(divs)*100:.1f}¢ · max {max(divs)*100:.1f}¢ · "
         f">5¢ in {sum(1 for x in divs if x>0.05)}/{n} games",
         "",
         "## Strategy: bet Kalshi toward the book when they diverge (hold to settlement)",
         "| min divergence | bets | expectancy/bet | win% | avg win | avg loss | worst | total |",
         "|---|---|---|---|---|---|---|---|"]
    for th in (0.0, 0.02, 0.03, 0.05, 0.08):
        e = expectancy(rows, th)
        if e:
            L.append(f"| ≥{int(th*100)}¢ | {e['n']} | **{e['exp']*100:+.2f}¢** | "
                     f"{e['winrate']*100:.0f}% | {e['avg_win']*100:+.1f}¢ | {e['avg_loss']*100:+.1f}¢ | "
                     f"{e['worst']*100:+.1f}¢ | {e['total']*100:+.0f}¢ |")
    # OOS check at the most permissive threshold that still has signal
    ed, eh = expectancy(split, 0.02), expectancy(hold, 0.02)
    L += ["", "## OOS (≥2¢ divergence, time-split)",
          f"- discovery: {ed['exp']*100:+.2f}¢/bet over {ed['n']} bets ({ed['winrate']*100:.0f}% win)" if ed else "- discovery: n/a",
          f"- holdout:   {eh['exp']*100:+.2f}¢/bet over {eh['n']} bets ({eh['winrate']*100:.0f}% win)" if eh else "- holdout: n/a"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(L) + "\n")
    print(f"Wrote {OUT}")
    print(f"  {n} games · Brier Kalshi {bk:.4f} vs DK {bb:.4f} · max div {max(divs)*100:.1f}¢")
    for th in (0.0, 0.03, 0.05):
        e = expectancy(rows, th)
        if e:
            print(f"   bet ≥{int(th*100)}¢ div: exp {e['exp']*100:+.2f}¢/bet · {e['winrate']*100:.0f}% win "
                  f"· avg win {e['avg_win']*100:+.1f} / loss {e['avg_loss']*100:+.1f} · n={e['n']}")


if __name__ == "__main__":
    main()
