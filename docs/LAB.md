# LAB.md — the operating manual for this strategy lab

This repo is a **strategy R&D lab** for Kalshi NBA trading. The loop:

> **define a strategy → backtest on all accumulated data → live-test on real games
> → review insights → retune (deliberately) → repeat.**

Read this first if you're Claude in a new session — it's how we work here.

## Roles (where things run)
- **GitHub repo** — source of truth for code **and** data (game logs, results
  ledger, insights, versioned params). Local + the cloud VM sync via git.
- **Local (this machine + Claude)** — research/dev: define strategies, backtest,
  analyze, retune, and run **REAL** trading (`run_real.py`, attended). Real money
  never leaves local.
- **Oracle VM** *(Phase D)* — always-on **paper** trading + live dashboard + auto
  data capture; pushes each game to the repo.
- **Claude (any session)** — reads accumulated data + ledger + insights, surfaces
  trends, proposes/implements strategies & param changes (user approves), owns the
  `auto_house` model *(Phase C)*.

## The learning approach (important)
- **User's strategies are NEVER silently auto-tuned.** Claude writes insights +
  proposed changes (with the data behind them) to `docs/INSIGHTS.md`; the user
  reviews; we apply changes deliberately to `strategy_params.json` (version bump +
  changelog note). This keeps understanding + an audit trail.
- **One Claude-owned model, `auto_house`** *(Phase C)*, auto-tunes itself with
  guardrails (only adopts params that beat current in backtest; versioned;
  **paper-only**) and runs in parallel for comparison.
- Small-data honesty: ~70 historical + few live games. Prefer **robust** params
  (good across many games) over peak backtest P&L. All edges provisional until
  many live games confirm.

## Commands
| Command | What |
|---|---|
| `python3 run_paper.py` | paper, pick a game (interactive) |
| `python3 run_paper.py --auto` | headless: auto-pick live game, stop at end (cloud) |
| `python3 run_paper.py --match OKC` | run a specific game by team |
| `python3 run_paper.py --replay` | replay a finished game |
| `python3 run_real.py` | REAL money (conviction, $25, attended, local only) |
| `python3 backtest.py` | backtest replayable strategies over all past games |
| `python3 summary.py [game_id]` | net P&L per strategy for one game |
| `python3 history.py [strategy]` | how strategies have fared over time (the ledger) |
| `python3 analyze.py` *(Phase B)* | trends → writes `docs/INSIGHTS.md` |
| `python3 tune.py` *(Phase B)* | param sweep over all data → robust settings |

## Where data lives
- `data/games/<date>_<away>_<home>/` — per game: `ticks.jsonl` (market+game on
  change), `trades.jsonl` (order flow), `plays.jsonl` (PBP+win prob),
  `paper_decisions.jsonl` / `real_decisions.jsonl` (every buy/sell: raw market +
  signal + *labeled* sim), `real_orders.jsonl` (real fills → slippage), `meta.json`.
- `data/results/strategy_history.jsonl` — the **performance ledger**: one row per
  strategy per game (live) + a dated backtest snapshot. Read with `history.py`.

## Adding a strategy (the pattern)
1. Subclass `Strategy` in `strategies.py`, set `key` / `label` / `needs` /
   `stake_frac`, implement `evaluate(ctx)`. Use `self.p("name", default)` for any
   tunable. `"orderflow"` in `needs` ⇒ live-only.
2. Add it to `REGISTRY`.
3. Add its params (incl `stake_frac`) to `strategy_params.json`.
4. It now flows automatically into `backtest.py`, `run_paper.py`, the ledger, and
   the dashboard.
See `docs/STRATEGIES.md` for the existing roster, rationale, and backtest results.

## Params = versioned config
All tunables + unit sizes live in `strategy_params.json` (code defaults are the
fallback via `self.p`). **Every change:** edit the value, bump `version`, add a
`changelog` entry (date + reason). `strategies.make(key)` loads them;
`strategies.params_version()` stamps the ledger so we know which params produced
which results.

## Deploy
- **Paper** → Oracle Always-Free VM, `run_paper.py --daemon` *(Phase D)*, pushes
  data to the repo. (GitHub Actions is the interim/backup path.)
- **Real** → local only, `run_real.py`, attended. Never in the cloud.
