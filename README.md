# Kalshi Sports Trading Lab

An autonomous research lab that asked one question: **can you beat Kalshi sports
game-winner markets with public data?**

We built the whole stack to find out: a live capture daemon, a fee-aware backtest engine,
an order-flow data moat, a calibration and edge-discovery harness, and an LLM research loop
that iterates on strategies on its own. Then we tested every angle we could reach.

**The answer is no.** Kalshi NBA and WNBA game-winner markets are efficiently priced against
every public signal we tried. This repo is the full system plus the honest writeup of how we
proved it, so you can run it, check our work, and skip the dead ends we already mapped.

## TL;DR of what we learned

| we tested | result |
|---|---|
| Trade the gap between ESPN win probability and the Kalshi price | No edge. The Kalshi mid and ESPN win-prob have an identical Brier score (0.1181). The market already prices in everything ESPN knows. |
| Does order flow predict the next price move? | No. Gross forward return is noise (~0) at every horizon; the market absorbs flow almost instantly. |
| Is a thinner market (WNBA) softer? | No, still efficient. |
| Cross-venue arbitrage vs the sharp sportsbook line (DraftKings via ESPN) | No gap. Kalshi tracks the de-vig book within ~2 cents (294 games), and is marginally sharper than the book. |
| Market making (capture the spread) | A real gross edge (about +0.35 cents per contract) but fee-gated: net is about +0.07 cents at Kalshi's 0.0175 maker fee. Too thin to be a business. |

The single most important thing we caught: **a look-ahead leak in our own backtest.** The
sim was filling at a price bar struck up to 60 seconds *before* the play it was reacting to,
which made worthless strategies look great (a control strategy that should lose money showed
+11.82 per game). Fixing it (fill at the bar that closes *after* the signal) made every
strategy go negative, which matched the independent calibration result. That fix saved us
from funding a fake edge. Lesson: leaks flatter you, and they scale into real losses.

## How it works

| | |
|---|---|
| Live capture | `run_paper.py` runs all strategies on paper against live Kalshi markets + ESPN play-by-play, logging every tick. A GCP free-tier VM runs this 24/7. |
| Backtest engine | `engine.py` replays finished games tick by tick, fee and slippage aware, no look-ahead. `backtest.py` runs the suite. |
| Data moat | `historical.py` builds a durable corpus: candles + play-by-play + win-prob + per-30s order-flow + official settlement, per game. |
| Edge discovery | `research/edge_discovery.py` mines calibration and mispricing, game-clustered, out-of-sample split, tail aware. `research/cross_venue.py`, `research/market_making.py`, `research/lead_lag.py` test the other angles. |
| Board | `boards.py` renders a static dashboard (strategies, live games, the research log) served on GitHub Pages. |
| Research loop | a headless LLM iterates on strategies daily, accountable to a north-star metric, fully paper-only. |

## The data (open)

`data/backtest/` holds 303 settled games (246 NBA + 57 WNBA), each a gzipped record of price
candles, ESPN play-by-play, win probability, condensed order flow, and the official Kalshi
result. `data/games/` holds live-captured games at full tick resolution. Use it freely.

## The writeups (the depth)

- `docs/EDGE_SCAN.md` — calibration + mispricing scan (why the gap has no edge)
- `docs/FLOW_SCAN.md` — order flow does not predict the next move
- `docs/CROSS_VENUE.md` — Kalshi vs the sharp sportsbook line
- `docs/MARKET_MAKING.md` — spread capture economics and the fee gate
- `docs/LAB_REVIEW.md` + `docs/RED_TEAM.md` — an internal audit and an adversarial review of our own claims
- `docs/QUANT_CHARTER.md` — the operating discipline (calibration first, disconfirmation first, guilty until proven)

## Run it

```
pip install requests
python3 historical.py          # build / refresh the corpus
python3 research/edge_discovery.py   # the calibration + mispricing scan
python3 backtest.py            # backtest the strategies (now leak-free)
python3 run_paper.py           # paper-trade a live game
```

Real-money code (`run_real.py`) exists but is capped, attended, and never automated. No keys
are in this repo.

## The honest conclusion

Public-data prediction does not beat an efficient real-money market. The edge, if it exists,
is structural (liquidity provision) or lives in markets the sharps ignore. We took those
learnings and moved the search to a different class of markets. This repo is the map of where
the treasure is not, which is worth a lot when everyone else is digging there.
