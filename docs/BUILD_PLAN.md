# BUILD PLAN — restructure to the 3-pillar automatic lab

Tracks everything to build/change so the system runs as `docs/prompt_ai_lab.md`
describes: **(1) auto capture+test all games, (2) the Board, (3) the auto lab
brain** — zero manual trigger; real money the only founder gate. Check items off
as we restructure. Goal: deploy with no dead/BS code.

## ✅ Done in the 2026-05-24 autonomous session
- **flow_confirm fixed** (disabled flow-flip exit → holds to settlement; +$3/game on captured games).
- **Multi-league discovery** (NBA + WNBA live; NCAA wired for season) + league tagging +
  `parse_ticker` rewritten (suffix-split — fixes WNBA) + ESPN feed per-sport + league-tagged game ids.
- **Concurrent multi-game daemon** (`run_paper.py --daemon` now captures ALL games at once,
  thread per game, isolated data + strategy sets, periodic push).
- **The Board** (`boards.py` → `boards.html`): paper-vs-live stats per strategy from the ledger,
  wallet-vs-floor, today's slate linking to per-game dashboards. State in `boards.json`
  (`--promote`/`--retire`/`--move`).
- **Lab cycle** (`lab_cycle.py`): the *deterministic, no-LLM* auto-improve routine —
  analyze → guarded auto-tune of `auto_house` → rebuild boards → investor report → commit.
  **Schedulable with plain cron** (no LLM needed for this layer).
- Per-game dashboards written by the daemon (`dashboards/<id>.html`) = the drill-in shards.

## ⏳ Remaining (bigger build / needs founder)
- **Isolated multi-strategy LIVE capital ledger** (real_broker is single-strategy) + per-wallet
  −50% floor. Needs real-money design + founder gate.
- **Cross-game edge/confidence allocation engine** (strategies still bet per-game independently).
- **Scheduling on the VM:** cron/systemd timer for `lab_cycle.py` (easy, deterministic) + the
  always-on daemon (done in `setup.sh`). The *creative* LLM brain (headless Claude inventing
  new strategy code) is a separate optional layer on top.
- **ESPN-less order-flow capture** (games with no ESPN match are currently skipped).
- **VM deploy itself** (founder runs `docs/DEPLOY_VM.md`) · SQLite only if scale demands.

## Where we are today (reuse, don't rebuild)
NBA single-game only, one game at a time. Have: `run_paper.py` (--daemon/--match/
--replay), `run_real.py` (single-strategy, attended), `backtest.py` (+--captured),
`strategies.py` (REGISTRY + `make`), `strategy_params.json` (versioned),
`engine.py` (LiveEngine/simulate/simulate_captured), feeds (Kalshi WS + ESPN
winprob), brokers (paper fees+slippage / real caps), `tradelog.py` (per-game
`data/games/`), ledger (`history.py`), `analyze.py`/`tune.py`/`auto_tune.py`/
`summary.py`, `dashboard.py` (single-game HTML), GitHub repo + Oracle VM docs.

---

## Pillar 1 — Capture & test ALL games, automatically
- [ ] **Multi-league discovery:** full daily basketball schedule across NBA / WNBA /
      NCAA-M / NCAA-W. Today `engine.list_live_games` is NBA-only (`KXNBAGAME`).
      Add the other Kalshi series + ESPN sport paths. Tag every game with its league.
- [ ] **Verify per-league data availability** (esp. ESPN win-prob for WNBA/NCAA —
      may not exist; fall back to price-only strategies where it doesn't).
- [ ] **Concurrent multi-game capture:** daemon must track *all* of a day's games
      at once, not one ticker. Either N `LiveEngine`s (one per game) or a capture
      manager; one shared dashboard + per-game folders.
- [ ] **Run all active strategies on every eligible game**, save per-game data
      (structure already exists). Keep capturing untraded games for the data moat.

## Pillar 2 — The Board (founder's source of truth)
- [ ] **Board state model:** which strategy is on which board (DEV/PAPER/LIVE/PAST),
      version, status, funded budget, wallet, floor. New `boards.json` + helpers,
      built on `strategy_history.jsonl` + `strategy_params.json`.
- [ ] **Board web view:** paper vs live stats side by side, #games, wallet-vs-floor
      health color, last updated. Served from the VM.
- [ ] **Today's slate view:** all games by league, which strategies trade each,
      running P&L.
- [ ] **Game drill-in "shard":** generalize `dashboard.py` to a per-game page
      (price vs win-prob, order flow, that strategy's trades).
- [ ] **Investor report:** daily narrative (P&L, notable trades, what changed, asks).
- [ ] **Promotion/retirement actions:** founder moves a strategy paper→live (fund +
      floor) or →past; reflected on the board.

## Pillar 3 — The automatic lab brain
- [ ] **Scheduled headless run:** `claude -p` / Agent SDK invoked by cron/systemd
      timer on the VM (daily to start). No human trigger.
- [ ] **Lab-cycle routine:** read data → mine trends (`analyze.py`) → propose &
      iterate strategies (params + new strategy classes) → **backtest-validate** →
      update boards → write report → commit.
- [ ] **Guardrails:** brain's auto changes apply to **paper only** and must pass a
      backtest gate before taking effect; **live = founder-gated**. Generalize
      `auto_tune.py` beyond `auto_house` to the paper portfolio (still gated).
- [ ] **Idea generation:** extend `analyze.py` feature set; optional web search for
      signals/data the brain deems valuable.

## Money, risk & execution
- [ ] **Isolated live capital ledger:** multi-strategy (today `real_broker` is
      single-strategy). Per-strategy wallet, `client_order_id` tagging, fill
      reconciliation — no capital/trade mixing. One Kalshi account (subaccounts
      entity-only — verified).
- [ ] **Hard floor per live allocation:** −50% → halt+lock+report (generalize
      `real_broker.max_loss` to a per-wallet floor).
- [ ] **Cross-game allocation engine:** rank candidate bets by edge net of fees +
      slippage; fund best first under budget + max-exposure caps; "no trade" valid.
- [ ] **Volume→slippage model:** calibrate from `real_orders.jsonl`; volume-aware
      pre-trade check. (Fees already modeled.)

## Deploy / storage / infra
- [ ] **Oracle VM:** multi-game daemon + dashboard server + scheduled brain + data
      push; extend `deploy/setup.sh` + `docs/DEPLOY_VM.md`.
- [ ] **Secrets on VM** + git push auth (done pattern); real money stays
      attended/local until floors+monitoring trusted (decide if/when on VM).
- [ ] **Storage:** JSONL now (fine/free); migrate to **SQLite** only if scale
      demands.

## Cleanup before deploy (no BS code)
- [ ] Decide GitHub Actions `paper.yml`: retire (VM daemon replaces it) or keep as backup.
- [ ] Reconcile `run_paper` flags with multi-game capture (one entry path).
- [ ] Keep docs consistent (charter, LAB, STRATEGIES, README, DEPLOY_VM).
- [ ] Dead-code sweep before the deploy commit.

## Founder decisions needed
Total capital + per-strategy live budget · sports-market legality in your state ·
off-limits leagues · brain cadence (daily/intraday) · real money on VM vs local.
