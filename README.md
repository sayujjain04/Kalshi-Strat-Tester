# Kalshi Sports Trading Lab

An open, honest answer to one question: **can you beat Kalshi sports game-winner markets
with public data?**

We built the whole stack (live capture, fee-aware backtest, order-flow data moat,
calibration and edge-discovery harness, an LLM research loop) and tested every angle. The
answer is **no**: Kalshi NBA and WNBA markets are efficiently priced against every public
signal we tried. This repo is the working system, the 303-game open dataset, and the
honest writeup so you can run it, check our work, and skip the dead ends.

**Read the story:** [`docs/STORY.md`](docs/STORY.md) (the long-form writeup with charts)
· [`docs/X_THREAD.md`](docs/X_THREAD.md) (the thread version).

## Findings at a glance

| we tested | result |
|---|---|
| Trade the ESPN win-prob gap vs the Kalshi price | No edge. Both have an identical Brier score (0.1181) over 118k observations. The market already prices in everything ESPN knows. |
| Does order flow predict the next price move? | No. Forward returns are noise at every horizon (~0 cents). |
| Is a thinner market (WNBA) softer? | No, still efficient. |
| Cross-venue arbitrage vs the de-vigged DraftKings line | No gap. Kalshi tracks the sharp book within ~2 cents over 294 games; never more than 4. |
| Market making (capture the spread) | A real gross edge (~+0.35 cents/contract) but the maker fee eats almost all of it (net ~+0.07 cents). |

The most important thing we caught was a look-ahead leak in our own backtest. A junk
control strategy that should lose money was showing **+$11.82 per game**. Fixing it (fill
at the bar that closes *after* the signal) made every strategy go negative, which matched
the calibration result. See `engine.fill_candle` and the [story](docs/STORY.md#the-bug-that-almost-fooled-me).

## Quick start

```bash
git clone https://github.com/sayujjain04/Kalshi-Strat-Tester.git
cd Kalshi-Strat-Tester
pip install requests matplotlib

# rebuild / refresh the 303-game corpus (reads from Kalshi public API + ESPN)
python3 historical.py

# the headline experiment: calibration + mispricing scan
python3 research/edge_discovery.py

# the leak-free backtest over the corpus
python3 backtest.py

# regenerate the charts in docs/charts/
python3 research/make_charts.py
```

To paper-trade live games (no API key needed; uses public Kalshi market data + ESPN):
```bash
python3 run_paper.py
```

Real-money trading code (`run_real.py`) exists but is capped, attended, and never
automated. **No API keys are in this repo. Real money is not in scope.**

## What the lab does

```
                        ┌──────────────────────────────┐
   Kalshi WebSocket ──► │   capture daemon (24/7)      │
   ESPN play-by-play ─► │   run_paper.py               │ ──► data/games/<id>/
                        └──────────────────────────────┘
                                                            ticks.jsonl
                                                            trades.jsonl
                                                            plays.jsonl
                                                            paper_decisions.jsonl
                                                            meta.json

   Kalshi REST ──► historical.py ──► data/backtest/*.json.gz   (the durable corpus)
                                          │
                                          ▼
                              engine.simulate (replay, fee-aware,
                                               anti look-ahead via fill_candle)
                                          │
                  ┌───────────────────────┼───────────────────────┐
                  ▼                       ▼                       ▼
            backtest.py          research/edge_discovery   research/market_making
            (suite)              calibration + scan         (spread capture econ)
                                          │                       │
                                          ▼                       ▼
                                 docs/EDGE_SCAN.md       docs/MARKET_MAKING.md
                                          │
                              metrics.py (north-star)
                                          │
                              boards.py ──► docs/*.html (static board)
```

In one paragraph: a capture daemon records every NBA and WNBA game tick by tick. A backtest
engine replays a finished game second by second, paying real Kalshi fees and crossing the
spread, with no look-ahead. A discovery harness (`research/edge_discovery.py`,
`research/cross_venue.py`, `research/market_making.py`, `research/lead_lag.py`) tests for
mispricings under that engine. A static board (`boards.py`) renders the results.

## Project layout

| | |
|---|---|
| **Run** | `run_paper.py` (live paper) · `backtest.py` (suite) · `historical.py` (corpus) |
| **Engine** | `engine.py` (live loop, replay, headless `simulate`, `fill_candle` anti-leak) |
| **Strategies** | `strategies.py` (registry: edge_naive, conviction, auto_house, wp_momentum, flow_confirm, late_fav, spread_cap, model_revert, run_momentum) |
| **Feeds** | `kalshi_feed.py` (WebSocket) · `espn_feed.py` (play-by-play + win prob) |
| **Brokers** | `paper_broker.py` (sim, fee + slippage) · `real_broker.py` (real orders, attended) |
| **Research** | `research/edge_discovery.py` · `cross_venue.py` · `market_making.py` · `lead_lag.py` · `make_charts.py` |
| **Reports** | `analyze.py` · `metrics.py` · `boards.py` |
| **Logging** | `tradelog.py` → `data/games/<id>/` |

## The open dataset

`data/backtest/` holds **303 settled games (246 NBA + 57 WNBA)**, each a gzipped record
containing:

| field | what |
|---|---|
| `candles` | 1-minute Kalshi mid + best bid / ask, full market lifetime |
| `plays` | ESPN play-by-play with wallclock, score, period, text |
| `wp_by_id` | ESPN win probability per play id |
| `flow` | per-30s condensed order flow (signed net contracts, volume, n_trades, max_trade, large-print volume) |
| `kalshi_result` | the official Kalshi settlement (`"yes"` / `"no"`) |

Use it freely under the MIT license. If you find an edge we missed, please open an issue.

## The writeups

- [`docs/STORY.md`](docs/STORY.md) — the long-form story with the methodology and charts
- [`docs/EDGE_SCAN.md`](docs/EDGE_SCAN.md) — calibration + mispricing scan
- [`docs/FLOW_SCAN.md`](docs/FLOW_SCAN.md) — order flow does not predict the next move
- [`docs/CROSS_VENUE.md`](docs/CROSS_VENUE.md) — Kalshi vs the sharp sportsbook line
- [`docs/MARKET_MAKING.md`](docs/MARKET_MAKING.md) — spread capture economics and the fee gate
- [`docs/LAB_REVIEW.md`](docs/LAB_REVIEW.md) + [`docs/RED_TEAM.md`](docs/RED_TEAM.md) — internal audit and an adversarial review of our claims
- [`docs/QUANT_CHARTER.md`](docs/QUANT_CHARTER.md) — the operating discipline (calibration first, disconfirmation first)

## Forking and extending

If you want to test your own prediction-market thesis with this stack, the path is:

1. **Reuse the data moat.** `historical.load_corpus()` gives you a list of `(game, data)`
   tuples with everything aligned. You do not have to rebuild the pipeline.
2. **Write your strategy as a class in `strategies.py`** (mirror `Conviction` or
   `EdgeNaive`). The engine handles fees, slippage, and the fill timing.
3. **Add it to `REGISTRY`** so `backtest.py` and `research/edge_discovery.py` pick it up.
4. **Run `research/edge_discovery.py` first.** Always check whether your signal is actually
   sharper than the market before writing strategy logic. If it is not, no rule on top will
   save you.
5. **Put a known junk control in your test.** If it ever wins, your test is lying.

For non-sports markets, the `kalshi_client.py` + the candle/markets fetching in
`historical.py` generalize cleanly. The only sport-specific bits are in `espn_feed.py`.

## Status

This repo is **archived as a research artifact** as of 2026-05-30. We've stopped the live
capture daemon and the autonomous research loop on this codebase; the lab's active work has
moved to a separate, private repo on a different class of markets (the same logic that
killed sports points to where an edge plausibly exists). This repo remains fully runnable
and the dataset stays open.

## License

MIT. See [LICENSE](LICENSE).

## Contact

Open an issue, or find me on X.
