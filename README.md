# Kalshi NBA Trading System

Runs strategies against live Kalshi NBA game-winner markets — on paper (all
strategies, simulated) or for real (one strategy, real money, hard caps). Uses
Kalshi for market data/order flow and ESPN for play-by-play + live win
probability. Captures every game's data for after-the-fact analysis and
strategy improvement.

## Run it

```
python3 run_paper.py                 # PAPER: pick a game, run all strategies on $100 each
python3 run_paper.py --replay        # replay a finished game (works any time)
python3 run_real.py                  # REAL MONEY: conviction only, $25 cap, kill switch
python3 backtest.py                  # backtest the replayable strategies over many past games
```

Run `run_paper.py` and `run_real.py` in two terminals to compare paper vs real on
the same game. `run_paper.py` writes the live dashboard to `dashboard.html`.

## Layout

| | |
|---|---|
| **Entry points** | `run_paper.py` (paper) · `run_real.py` (real $) · `backtest.py` |
| **Orchestration** | `engine.py` (live loop, replay, headless `simulate`) |
| **Strategies** | `strategies.py` (+ `docs/STRATEGIES.md` for the rationale & backtest) |
| **Accounting** | `paper_broker.py` (sim, with fees+slippage) · `real_broker.py` (real orders) |
| **Data feeds** | `kalshi_feed.py` (WS market+book+tape) · `espn_feed.py` (PBP+win prob) |
| **Kalshi access** | `kalshi_client.py` · `kalshi_creds.py` (key) |
| **Logging** | `tradelog.py` → `data/games/<id>/` |
| **Dashboard** | `dashboard.py` → `dashboard.html` |
| **Docs** | `docs/STRATEGIES.md` (canonical) · `docs/nba_strategies_handoff.md` (original spec) |

## Per-game data (`data/games/<date>_<away>_<home>/`)

| file | what |
|---|---|
| `ticks.jsonl` | market+game state on every change (price, book, win prob, score) |
| `trades.jsonl` | every public trade once — the order-flow record |
| `plays.jsonl` | ESPN play-by-play: exact score + win prob + text per play |
| `paper_decisions.jsonl` | paper strategy opens/closes (raw market + signal + **labeled** sim) |
| `real_decisions.jsonl` | real strategy opens/closes |
| `real_orders.jsonl` | real order attempts: requested vs actual fill → slippage |
| `meta.json` | game summary (teams, final score, per-strategy P&L) |

Logging is **event-based** (writes on change, stops post-game) so a full game is
~1–2 MB, not 30 MB. Slippage in the paper sim is a labeled *assumption*, never
stored as if it were a real fill; `real_orders.jsonl` is the ground truth for
calibrating it.

## Key facts learned
- **Fees are real**: ceil(7% × contracts × price × (1−price)), maxed near 50¢, free at settlement.
- **Hold, don't scalp**: with a persistent edge, holding to settlement beats repeated round trips (fees kill churn).
- **`conviction`** (buy the cheap model-favorite, hold to settlement) is the validated earner.
- See `docs/STRATEGIES.md` for the full strategy roster, backtest results, and risk sizing.
