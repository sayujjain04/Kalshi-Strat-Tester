# NBA Live-Trading Strategy Specs

These specs are written to slot in alongside **EdgeFade1C** and **EdgeFade2C**, which already cover the mean-reversion / aligned-edge family completely — those are the canonical "Mean Reversion to Model" strategy and are not rewritten here. What follows are the strategies EdgeFade does not cover, each in the same format: thesis, entry, exit, risk stops, game-state guards, and lag handling.

---

## Shared assumptions (lifted out so they aren't repeated five times)

**The lag principle.** ESPN game data — score, `win_prob_home`, `model_p_yes`, runs — is up to ~15 seconds stale and updates per-play. Kalshi price, book, and trades are sub-second. The asymmetry has a direction: the price leads, the model lags. So any comparison of the two is comparing a fresh number to a stale one, and the error is systematic rather than random. The rule that governs every strategy below: **use the slow ESPN data for context and entry framing, use the fast Kalshi data for danger detection and exits.** Never let a lagged number be the thing that keeps a position open while the live price is moving against it.

**Game-state guards.** Five edge cases break naive rules and every strategy must respect them:

- **Settlement cliff.** As the `clock` approaches 0:00 in the final period or any OT, the book thins and the spread blows out — you can no longer reliably exit. No strategy opens inside the final 60 seconds (90 for Run Fade), and all force flat before the cliff.
- **Garbage time vs. live game.** Always read score margin and time remaining *together*. A 6-point lead with 5:00 left is genuinely live; a 20-point lead with 5:00 left is decided. Neither number means anything alone.
- **Dead-data window.** ESPN refreshes ~15s, the loop runs ~2s, so roughly 7 of every 8 evaluations see identical game data. Game-derived signals must only re-fire when ESPN's timestamp actually changes. This belongs at the engine level, implemented once, not re-coded per strategy.
- **Status transitions.** Only act when `status == in`; nothing opens in pre or post. A frozen clock with no new plays is a stoppage (timeout / period break) — don't misread a flat win-probability as a real signal.
- **Overtime.** `period` can exceed 4 and the `clock` resets to 5:00. Any logic keyed to "4th quarter" must generalize to "final regulation period or any OT."

---

## Run Fade

**Thesis.** Live NBA markets overreact to scoring runs, and runs mean-revert. An 8-0 burst rarely continues; the Kalshi price overshoots the true win-probability shift and fades back as the run breaks. This strategy bets against the running team. Importantly, it does **not** use `model_p_yes` at all — it triggers off the ESPN run signal and the live Kalshi price — which makes it robust to ESPN model error.

**Entry.** `status == in`, at least 90 seconds remaining in the current period, no open position. `run_team` shows one team on an unanswered run with `run_size` ≥ 8 (≥ 10 in the 4th or OT), and that team's Kalshi price has spiked ≥ 4¢ during the run on the live candle. Open the opposite side — NO on the running team — at the ask.

**Exit.** The run breaking is the primary profit-take: the opponent scores, so `run_size` resets or `run_team` flips. Also take profit if price reverts 4¢ toward the pre-run level. Hard stop if price moves another 5¢ in the run's direction — the run is real, not noise, so get out and don't fight it. Time stop at 2.5 minutes. Forced flat at 90 seconds remaining.

**Game-state guards.** Require ≥ 90 seconds left, because a late-game run is often the *actual* deciding sequence rather than an overreaction — fading a real closing run is how you lose. Raise the threshold to `run_size` ≥ 10 in the 4th/OT for the same reason. Ignore any run that bridges a period break, since that "run" is an artifact of the clock stopping rather than continuous play.

**Lag handling.** The lag works in this strategy's favor: by the time ESPN reports the run, the play happened up to 15 seconds ago and the price has already spiked, so the fade signal is conservative rather than premature. The one residual risk is that the run may already be over — the opponent just scored and ESPN doesn't know yet. Guard against it by not fading a run whose price spike has *already fully reverted* on the live Kalshi candle: if price is back near pre-run levels, the market has moved on, so skip.

**Replayable.** Yes — run, score, and price candles all replay.

---

## Late-Game Favorite Lock

**Thesis.** Late in a comfortable game the outcome is nearly decided, but the market sometimes leaves a few cents on the table because volume thins out. Buying the heavy favorite slightly cheap and holding to settlement (or near it) is a low-variance, high-probability edge.

**Entry.** Final regulation period or any OT, between ~4:00 and ~1:00 on the `clock` — not closer than 60 seconds, because past that the price is already ~$0.99 and there's nothing left to capture or exit into. `model_p_yes` ≥ 85% for one team, that team's Kalshi price ≤ 80¢, no open position. Buy YES on the favorite at the ask.

**Exit.** Settlement is the intended exit — this is a hold-to-win. Also exit at 95¢ to capture most of the move without settlement-cliff exposure. Bail if `model_p_yes` drops below 75% (the lead is evaporating), or — the more important trigger — if the favorite's live Kalshi price drops sharply, ≥ 5¢ off its recent candle high, even while `model_p_yes` is still high.

**Game-state guards.** Verify the lead is structural, not just a favorable snapshot: cross-check that score margin is comfortable relative to time, roughly margin ≥ 3 points per remaining minute. Abort entry if `run_team` is the *trailing* team on a live run ≥ 8 — that is exactly the comeback that turns an 85% into a 60%.

**Lag handling.** Division of labor by data speed. The entry leans on `model_p_yes` ≥ 85%, which on a stable late lead is slow-moving and harmless to be 15 seconds stale about. But the danger — a comeback — shows up on the fast Kalshi price before ESPN's model catches up. So the entry trusts the slow data while the abort and exit trust the fast data. The ≥ 5¢ live-price-drop exit is specifically what protects against ESPN reporting the collapse too late.

**Replayable.** Yes.

---

## Win-Prob Momentum *(flagged — weakest of the set)*

**Thesis, stated honestly with its problem.** The idea is to buy a team while ESPN's model is rising faster than the Kalshi price, before price catches up. But this only has an edge if ESPN is *faster or more accurate* than the market — and ESPN is slower. So the setup "model high, price low, model right" is, more often, actually "price already dropped on a play ESPN hasn't processed, and the model is about to fall to meet it." Run this **only** as an empirical counter-test to Run Fade — they are opposite bets on whether this market over- or under-reacts to a price move, and running both lets the data settle the argument — and **only with the Order-Flow Filter attached.** Do not give it standalone attention.

**Entry.** `status == in`, not within the final 60 seconds, no open position. ESPN `win_prob_home` has moved ≥ 8 points toward one team over the last ~60 seconds of game time (tracked across ESPN updates, not loop ticks), the team's timestamp-aligned `implied_p_yes` is still ≥ 5¢ below its `model_p_yes`, and — required, not optional — the Order-Flow Filter agrees. Open YES at the ask.

**Exit.** Take profit when price converges to within 2¢ of `model_p_yes`. Exit if `model_p_yes` stalls or reverses for 2 consecutive ESPN updates (momentum died). Time stop at 3 minutes. Hard stop if price moves 5¢ against entry. Forced flat at 60 seconds.

**Game-state guards.** Suppress in the final 60 seconds (settlement cliff). Skip during stoppages — win-probability won't move on a dead clock, so don't read a flat number as "momentum died" and bail prematurely.

**Lag handling.** This is the strategy most exposed to the lag, by construction. Timestamp-alignment on the entry comparison is mandatory: compare ESPN's number to the Kalshi mid *as of ESPN's stamp*, not the live mid. Even with that, the premise fights the data direction, which is why the order-flow gate is required rather than optional — it refuses the trade when live flow disagrees, which is precisely the adverse-selection guard.

**Replayable.** The entry and exit replay if timestamp-aligned, but the required order-flow gate is live-only — so in practice this is live-only to run as intended.

---

## Spread Capture *(live-only, exploratory)*

**Thesis.** When the book is temporarily lopsided during a quiet stretch, there may be room to enter on the favorable side. Marginal by nature — you pay the spread on both entry and exit — so treat it as exploratory rather than a core earner.

**Entry.** `status == in`, mid-game (avoid the final 3 minutes, where spreads widen naturally near settlement and you'd misread that as opportunity), `spread` ≥ 4¢, low recent `trade_flow` (quiet book), `model_p_yes` within 3¢ of mid (model agrees the mid is roughly fair), no open position. Enter on the side the book is leaning away from.

**Exit.** Take profit at 3¢ in your favor. Exit if the spread re-tightens to ≤ 2¢ — the inefficiency is gone. Exit if any run starts (`run_size` ≥ 6 — the quiet stretch is over). Time stop at 90 seconds. Forced flat 3 minutes out.

**Game-state guards.** "Quiet" must be confirmed on live Kalshi data — low `trade_flow`, flat recent candle — not on ESPN.

**Lag handling.** Essentially lag-immune: it operates deliberately in stretches where nothing is happening, so there's nothing for ESPN to be late about. The `model_p_yes` check is a sanity filter, not a timing-sensitive signal.

**Replayable.** No — uses spread/book state, which has no historical depth.

---

## Order-Flow Filter *(live-only — a gate, not a standalone strategy)*

**Purpose.** This isn't a strategy on its own; it's a confirmation gate layered on the model-vs-price strategies (Win-Prob Momentum, and optionally EdgeFade). Conceptually it's the structural fix for the lag problem: `imbalance` and `trade_flow` are pure live Kalshi signals, so requiring them to agree means you only take a model-driven trade when the fast data confirms it. You refuse to bet against live order flow even when the lagged model tempts you to.

**Gate condition.** Before the host strategy opens, require `imbalance` and `trade_flow` to point the same direction as the intended trade — don't buy YES into heavy NO flow or negative `trade_flow`, and vice versa.

**Added exit.** On top of the host strategy's exits, early-out if `trade_flow` flips hard against the open position for 2 consecutive ticks (smart money reversed).

**Lag handling.** It *is* the lag antidote — that's the whole point of it.

**Replayable.** No — `imbalance`, `trade_flow`, and `trades` have no historical depth data.

---

## Suggested testing sequence

Validate **Run Fade** and **Late-Game Favorite Lock** first in replay — they're the cleanest, lowest-risk, and least dependent on ESPN's model being correct. Run **EdgeFade2C** alongside them (then **EdgeFade1C**), since they're already specced and replay perfectly. Treat **Win-Prob Momentum** only as the empirical foil to Run Fade, and only with the Order-Flow Filter attached. Save **Spread Capture** and the **Order-Flow Filter** for live testing once there's a replay baseline, since neither can be validated on historical data.

Two engine-level notes that apply across everything: the **dead-data guard** (only re-fire game-derived signals when ESPN's timestamp changes) and the **timestamp-alignment** logic both belong in the engine, implemented once, rather than re-coded in each strategy. And the binding constraint on the whole set is the ESPN poll interval — dropping it from 15s to ~5s shrinks every lag window by two-thirds and is probably higher-value than any single strategy refinement, so it's worth doing before trusting the model-dependent strategies with real attention.
