#!/usr/bin/env python3
"""
lab_cycle.py — the automatic lab research cycle (what the scheduled brain runs).

One pass: refresh insights → guarded self-tune of the auto_house model → rebuild
the boards → write a dated investor report → commit. This is the entry point a
cron/systemd timer (or a scheduled headless Claude) invokes; no human trigger.

    python3 lab_cycle.py                 # full cycle + commit
    python3 lab_cycle.py --no-commit     # run, don't commit
    python3 lab_cycle.py --no-tune       # skip the auto_house auto-tune
"""
import datetime, json, os, subprocess, sys

import analyze
import auto_tune
import boards
import strategies as strat

ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(ROOT, "data", "results")


def write_report():
    live, bt = boards.strategy_stats()
    day = datetime.date.today().isoformat()
    L = [f"# Lab report — {day}", "",
         f"_params v{strat.params_version()}_", "",
         "## Strategy performance (backtest snapshot · live forward-test)"]
    for key in sorted(bt, key=lambda k: -(bt[k].get("per_game") or 0)):
        b, lv = bt[key], live.get(key, {})
        L.append(f"- **{key}** — backtest {b.get('per_game', 0):+.2f}/game; "
                 f"live {lv.get('net', 0):+.2f} over {lv.get('games', 0)} games "
                 f"({lv.get('w', 0)}W/{lv.get('l', 0)}L)")
    try:
        cfg = json.load(open(strat._PARAMS_PATH))
        last = (cfg.get("changelog") or [{}])[-1]
        L += ["", "## Latest param change",
              f"- v{last.get('version')} ({last.get('date')}): {last.get('note')}"]
    except Exception:
        pass
    g = boards.todays_games()
    game_lines = [f"- {x['id']}" + (f" — FINAL {x['final']}" if x.get("final") else "")
                  for x in g] or ["- none"]
    L += ["", "## Today's games", *game_lines]
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"report_{day}.md")
    open(path, "w").write("\n".join(L) + "\n")
    return path


def main():
    args = sys.argv[1:]
    commit = "--no-commit" not in args
    tune = "--no-tune" not in args
    print(f"== LAB CYCLE {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M UTC} ==")

    print("1/4 analyze → docs/INSIGHTS.md")
    analyze.main()

    if tune:
        print("\n2/4 guarded auto-tune of auto_house (paper-only)")
        auto_tune.retune(dry=False)
    else:
        print("\n2/4 auto-tune skipped")

    print("\n3/4 rebuild boards.html")
    boards.render()

    print("\n4/4 investor report")
    rpt = write_report()
    print(f"  wrote {rpt}")

    if commit:
        for cmd in (["git", "add", "data/", "docs/INSIGHTS.md", "strategy_params.json", "boards.json"],
                    ["git", "commit", "-m", f"lab cycle {datetime.date.today().isoformat()}"],
                    ["git", "push"]):
            subprocess.run(cmd, check=False)
        print("committed + pushed")
    print("== cycle done ==")


if __name__ == "__main__":
    main()
