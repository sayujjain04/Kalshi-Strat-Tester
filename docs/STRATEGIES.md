# Strategies — canonical reference

Source of truth for `strategies.py`. (Older `nba_strategies_handoff.md` is the
design spec; where they disagree, **this file wins**. Handoff's "EdgeFade1C/2C"
= our `model_revert` + `edge_naive`; handoff's "Run Fade" was **inverted to
`run_momentum`** after backtesting — see below.)

```
python3 run_paper.py                                   # live, all 7 strategies
python3 run_paper.py --replay                           # test on a finished game
python3 run_paper.py --strategies model_revert,run_momentum,late_fav
python3 backtest.py                                   # backtest the 4 replayable ones over 69 games
```
Each strategy has its own $100 and **its own risk size** (below), holds one
position at a time, fills at the real bid/ask, and logs a plain-English reason.

---

## Backtest results NET OF FEES + SLIPPAGE (69 playoff games)

Costs are now modeled: **Kalshi fee = ceil-to-cent(7% × contracts × P × (1−P))**
(verified against a real fill; zero at settlement), plus **0.5¢ slippage** per
fill. This changed everything — most strategies were profitable *only* because the
old sim assumed free, perfect fills.

| Strategy | Stake | Win% | $/game (net) | Prof. games | Worst | Verdict |
|---|---|---|---|---|---|---|
| **`conviction`** | 25% | 49% | **+$6.57** | **48/69** | −$12 | ✅✅ **the earner — run this** |
| `late_fav` | 35% | **100%** | +$0.89 | 15/69 | **$0** | ✅ bulletproof but rare |
| `model_revert` | 10% | 42% | +$0.65 | 19/69 | −$9 | ⚠️ tiny edge (Kelly 0.08) |
| `run_momentum` | 5% | 28% | −$0.40 | 10/69 | −$4 | ❌ loses after fees |
| `edge_naive` | 10% | 52% | +$13.41 | 56/69 | −$10 | ❌ replay artifact — ignore |

**The design that beats fees (→ `conviction`).** The fee is maxed near 50¢
(~4–5¢/contract round trip) and tiny near the edges, and **settlement is free**.
So the winning shape is: buy the model-favored side when it's a strong favorite
trading cheap, then **hold to settlement** — one cheap entry fee, no exit fee, big
capture. `conviction` generalizes that across the whole game (not just the final
5 min like `late_fav`) and bails early (model <65%) to cap losses: avg win **+$9**
vs avg loss **−$2.17**. It's the only strategy that both beats costs *and* fires
often (136 trades, 48/69 games green).

**Why the others lose/marginal.** `model_revert`/`run_momentum`/`edge_naive` trade
*often near 50¢*, so fees + slippage eat the thin edge. `edge_naive`'s big number
is a *latency-free* replay artifact — ignore it.

**Risk sizing (Kelly, from per-trade win/loss).** `conviction` Kelly = 0.37 → sized
at **25% (≈⅔ Kelly)**; push to 37% for max growth at higher variance. `late_fav`
sized 35% (near-certain, near-zero downside). The marginal/losing ones get token
stakes so they barely risk anything.

**Bottom line for real money: run `conviction`** (optionally + `late_fav`).

---

## The big finding: ride runs, don't fade them

The handoff specced "Run Fade" (bet *against* a team on a run). Backtesting it
across 69 games: **2% win rate, −$280, lost in all 69 games.** In playoff ball,
runs *continue* — the market under-reacts. Inverting to **ride** the run: **65%
win, +$160.** So `run_momentum` bets *with* the run by default. (`ride=False`
param restores the original fade thesis if you ever want to A/B it.)

`late_fav` was also far too tight (fired 4× in 69 games). Loosening the cheap-
favorite ceiling 80¢ → 90¢ and widening the window keeps the 100% win rate while
firing 4× as often.

---

## The lag rule (why the design is what it is)

ESPN data (score, runs, win-prob) is ~5–15s stale and per-play; Kalshi
price/book/trades are sub-second. **Price leads, model lags.** So: slow ESPN data
for context/entry, fast Kalshi data for danger/exits. Built once in the engine,
shared by all:
1. **Timestamp alignment** — compare model to the price *as of the model's
   timestamp* (`aligned_implied`), not the live price.
2. **Persistence gate** — act only on a gap holding the same direction ≥2 ESPN
   updates and ≥30s.
3. **Dead-data guard** — game-derived entries re-fire only when ESPN advanced
   (`game_fresh`); a frozen clock (stoppage) won't trigger anything.
4. **ESPN poll = 5s** (down from 15) and **settlement-cliff guards** (force-flat
   before the end-of-game liquidity cliff).

---

## One-line summaries

| Strategy | Plain English | Replay? |
|---|---|---|
| **`model_revert`** | Price drifts from ESPN's win-prob and *stays* there 30s+ → bet it snaps back. Main lag-safe earner. | ✅ |
| **`run_momentum`** | Team rips an 8-0 run → ride it (runs continue in the playoffs). | ✅ |
| **`late_fav`** | Late in a decided game, buy a still-cheap heavy favorite; bail instantly if its price drops. | ✅ |
| **`edge_naive`** | `model_revert` with no lag protection — kept only as a live control. | ✅ |
| **`wp_momentum`** | Model swings hard toward a team, price lags, *and live flow agrees* → ride. | ⚠️ live |
| **`spread_cap`** | Quiet stretch + wide spread → lean the lopsided book. | ⚠️ live |
| **`flow_confirm`** | The lag-safe edge, only when live order flow confirms it. | ⚠️ live |

---

## Detail (entry · exit · key params)

### `model_revert` ✅ — stake 30%
- **Entry:** model vs *aligned* price ≥8¢ apart, gap held ≥30s/2+ updates → toward model.
- **Exit:** converge ≤3¢ · 4-min cap · 5¢ hard stop · force-flat 60s before end.
- `enter_edge=0.08 exit_edge=0.03 persist_s=30 hard_stop=0.05` *(kept at 8¢ for lag safety even though 6¢ tested higher — the extra trades are the lag-vulnerable ones)*

### `run_momentum` ✅ — stake 25%
- **Entry:** team on a run ≥8 (≥10 in 4th/OT), ≥90s left, didn't bridge a period break, price started moving its way → **ride** (bet with the run).
- **Exit:** run breaks · +4¢ profit · 5¢ hard stop · 2.5-min cap · force-flat 90s.
- `run_threshold=8 run_threshold_late=10 revert_target=0.04 hard_stop=0.05 ride=True`

### `late_fav` ✅ — stake 40%
- **Entry:** final period/OT, 1:00–5:00 left, a side's model ≥85% but price **≤90¢**, lead structural (≥3 pts/min), trailing team not on a run ≥8.
- **Exit:** lock at 95¢ · **bail if favorite's live price drops ≥5¢ off its peak** · bail if model <75% · force-flat 60s · else hold to settlement.
- `fav_prob=0.85 price_max=0.90 window_lo=60 window_hi=300 drop_exit=0.05`

### `edge_naive` ✅ — stake 20% (control)
- Like `model_revert` but uses the **live** price and **no** persistence. Diagnostic only — do not trust its live P&L.

### `wp_momentum` ⚠️ live — stake 15%
- Model swung ≥8pts/60s, aligned price ≥5¢ behind, **live flow agrees** (required) → ride. Exits: converge ≤2¢ · momentum dies · 3-min cap · 5¢ stop · force-flat 60s.

### `spread_cap` ⚠️ live — stake 15%
- Mid-game, spread ≥4¢, quiet book, model ≈ mid → lean the lopsided side. Exits: +3¢ · spread ≤2¢ · run ≥6 · 90s cap · force-flat 3min. (May rarely fire — NBA spreads are tight.)

### `flow_confirm` ⚠️ live — stake 20%
- The `model_revert` edge **plus** live flow confirming. Exits: converge ≤2¢ · flow flips against 2 ticks · 5¢ stop · force-flat 60s.

---

## How to test / run today
- **Backtest the 4 replayable:** `python3 backtest.py` (uses cached game data; instant after first run).
- **Watch one game end-to-end:** `python3 run_paper.py --replay`.
- **Run live today:** `python3 run_paper.py` → pick the game → leave it running. The
  3 live-only strategies only do anything once there's real book/tape; `late_fav`
  only fires in the final ~5 minutes.

## Adding / tuning a strategy
Subclass `Strategy`, set `key`/`label`/`needs`/`stake_frac`, implement
`evaluate(ctx)`, add to `REGISTRY`. Tune via `params` and re-run `backtest.py`'s
`run_suite`. `"orderflow"` in `needs` ⇒ live-only.
