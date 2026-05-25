#!/usr/bin/env python3
"""
auto_tune.py — Claude-owned auto-tuning for the `auto_house` model ONLY.

Grid-searches auto_house's params over ALL historical games and adopts a new
config **only if it beats the current one by a margin** (guardrail). Every
adoption bumps strategy_params.json's version and adds a changelog entry, so the
auto-model's evolution is fully auditable. Paper-only — never touches real money,
never changes the user's hand-built strategies.

    python3 auto_tune.py            # search + adopt if clearly better
    python3 auto_tune.py --dry      # search only, write nothing
"""
import datetime, itertools, json, sys

import backtest
import strategies as strat

KEY = "auto_house"
MARGIN = 1.10        # new must beat current score by ≥10% to be adopted
GRID = {
    "edge":              [0.04, 0.06, 0.08],
    "bail_prob":         [0.60, 0.65, 0.70],
    "fav_min":           [0.70, 0.75, 0.80, 0.85],
    "final_period_only": [False, True],
}


def score(a):
    """Robust objective: per_game − 0.5·|worst_game|. Matches the north-star
    penalty exactly so auto_tune optimises the same metric the board reports."""
    per = a["pnl"] / a["games"] if a["games"] else 0
    return per - 0.5 * abs(a["worst"])


def _eval(combo, dataset):
    agg = backtest.run_suite(lambda k: strat.make(k, overrides=combo), [KEY], dataset)
    return agg[KEY]


def retune(dry=False):
    dataset = backtest.load_all()
    cur = strat.load_params().get(KEY, {})
    cur_combo = {p: cur.get(p) for p in GRID}
    cur_stats = _eval(cur_combo, dataset)
    cur_score = score(cur_stats)
    print(f"current {cur_combo}: {cur_stats['pnl']/cur_stats['games']:+.2f}/game "
          f"worst={cur_stats['worst']:+.2f} score={cur_score:.2f}\n")

    best, best_score, best_stats = None, cur_score, cur_stats
    for vals in itertools.product(*GRID.values()):
        c = dict(zip(GRID, vals))
        s = _eval(c, dataset)
        sc = score(s)
        flag = " *" if sc > best_score else ""
        print(f"  {c}: {s['pnl']/s['games']:+.2f}/game worst={s['worst']:+.2f} score={sc:.2f}{flag}")
        if sc > best_score:
            best, best_score, best_stats = c, sc, s

    if not best or best_score < cur_score * MARGIN:
        print(f"\n🔒 Guardrail: nothing beats current by ≥{int((MARGIN-1)*100)}% — keeping current.")
        return False
    print(f"\n✅ ADOPT {best}  (score {best_score:.2f} > {cur_score:.2f}×{MARGIN})")
    if dry:
        print("(dry run — strategy_params.json not changed)")
        return False
    cfg = json.load(open(strat._PARAMS_PATH))
    cfg["strategies"][KEY].update(best)
    cfg["version"] += 1
    cfg.setdefault("changelog", []).append({
        "version": cfg["version"], "date": datetime.date.today().isoformat(),
        "note": f"auto_house auto-tuned → {best} "
                f"({best_stats['pnl']/best_stats['games']:+.2f}/game over {len(dataset)} games)"})
    json.dump(cfg, open(strat._PARAMS_PATH, "w"), indent=2)
    print(f"Updated strategy_params.json → version {cfg['version']} (auto_house only)")
    return True


if __name__ == "__main__":
    retune(dry="--dry" in sys.argv)
