# Maintenance Checklist (run FIRST, every iteration)

The autonomous loop (`deploy/research_prompt.md`) and any interactive Claude session
work through this list **before** doing new research. It's the system's hygiene routine
so nothing rots. **To add a new recurring check, just add a bullet here** — the loop will
pick it up automatically next run.

Keep it cheap: most items are quick reads/edits. Only act when something's actually due.

## Every run
1. **Close resolved escalations.** Read `docs/OPEN_QUESTIONS.md`. For each `## Open`
   item, if it's actually done, move it to `## Closed` with a one-line resolution.
   Don't leave stale items lighting up the founder's Needs-You panel.

2. **Enforce pre-registered kill-switches.** For every strategy on PAPER/LIVE that was
   adopted with a falsification condition (see `strategy_params.json` changelog +
   `data/research/experiments.jsonl`), check that condition against CURRENT forward data.
   If a condition is breached (e.g. "retire if OOS win% < 55%" once n is adequate),
   **retire the strategy** (`boards.py --retire <key>`) and log it. A pre-registered kill
   that never gets checked is theater. (Note: only act once the forward sample is large
   enough to judge — otherwise note "still underpowered, n=X".)

3. **Update the experiment ledger.** In `data/research/experiments.jsonl`, refresh
   `sample_n` as data grows and flip `status` (open→validated/killed) when evidence is
   sufficient. Don't let experiments sit "open" forever with no verdict.

4. **North-star regression guard.** Compare the latest `data/research/metrics.jsonl`
   north-star to the prior run. If it **dropped**, diagnose why before starting anything
   new (overfit adopted last run? regime shift? a bad param?) and fix/revert.

5. **Loop health.** Confirm the corpus is current and forward bets are climbing toward
   ~100. If `historical.py` found 0 new games for many days during a season, or metrics
   stopped logging, flag it in `OPEN_QUESTIONS.md`.

6. **Finalize stuck games.** Run `python3 deploy/finalize_game.py --all` — closes out any
   game whose Kalshi market settled but whose capture didn't finalize (ESPN can stay "in"
   after settlement), which otherwise shows LIVE forever and wastes capture. (Now also in
   the daily loop.)

## Occasional (when relevant)
6. **Doc/board hygiene.** Remove or update stale docs; confirm board drill-in links
   resolve; delete orphaned scripts. Don't accumulate cruft.
7. **Credit discipline.** Glance at `data/research/credits.jsonl` month total; stay
   within budget; don't redo expensive backtests that haven't changed.
8. **Provenance.** Any factual claim about a data source / endpoint / fee schedule is
   verified live, not from memory (see the project's data-provenance rule).

## How to add a check
Add a numbered bullet above with: what to check, how to tell it's due, and what to do.
That's it — the loop reads this file at the start of every run.
