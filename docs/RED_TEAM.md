# RED_TEAM.md — hostile review of the four claims (2026-05-27)

Reviewer: adversarial quant + systems audit. Method: read the real code, measured against
the live corpus and a running system. Flow fields treated as transitional (a
`historical.py --flow` backfill is running, PID 12607) and excluded from data verdicts;
checks focus on stable fields (candles/plays/win_prob/settlement) and on code.

## Verdict summary
Three of the four claims hold up well; one is oversold. The system genuinely IS efficient
for a solo lab (0.30s board push verified, no re-sim on the hot path) and IS fast enough
for live decisions (real-time WS price, 2s eval, live path correctly aligns price to the
model timestamp — it does NOT inherit the C1 leak). The cleanup work is real: all C1–C4
fixes are present AND correctly reasoned, not cargo-culted. The weak claim is "data is
complete and model-ready": completeness is real and impressively honest (settlement 97.6%
reproduced, ESPN agreement 240/240 reproduced), but "model-ready" is overclaimed — the
backtest shows EVERY strategy is net-negative across 246 games, i.e. the corpus has so far
proven the absence of an edge, not the readiness to train one, at an n that is too small
and too autocorrelated to validate a durable signal. The thing Claude most underrates: its
own "latency doesn't matter" claim is logically unsound for the microstructure pivot it is
about to chase.

---

## CLAIM 1 — "The system is EFFICIENT." → **UPHELD**

- **Board push is real-time-cheap and does NOT re-simulate.** `python3 boards.py --quick`
  (the 5-min daemon push, run_paper.py:126) measured **0.30s real** (matches the asserted
  0.28s). `boards.compute_stats()` reads the backtest snapshot straight out of the ledger
  (`boards.py:141-142`, `r.get("source")=="backtest"`) — no simulation on the push path.
  Verified.
- **Sizes check out.** Working files ~45 MB (232 MB tree − 187 MB `.git`); corpus 7.8 MB.
  The 187 MB `.git` bloat is real and its cause is concrete: `git rev-list --objects` shows
  the top blobs are repeated 8 MB versions of `data/games/*/trades.jsonl`. Pack is 134 MiB.
  Push is incremental (new objects only), so the bloat bites only on a fresh clone/Pages
  cold-build, which is rare on a long-lived VM — deferring the force-push is a defensible
  call, exactly as claimed.
- **S4 quantified, and it's a footnote.** `analyze.py:91-93` does re-run the full backtest
  uncached every cycle: measured **~7.7s** (0.96s load_all of 246 games + 6.69s run_suite ×
  9 strategies), under CPU contention from the running backfill. For a *daily* research
  loop, 7.7s costs nothing. Real, but not worth fixing.
- **S3 (3 sim paths) is a correctness nuance, not just redundancy** — see Claim 2.

Severity: footnote. Nothing here costs money, data, or meaningful iteration speed.

## CLAIM 2 — "Fast enough for live paper decisions." → **UPHELD** (with one logic flaw)

- **The live trading price is real-time WS, not the 30s candle poll.** The decision loop
  reads `self.market_state.snapshot()` (engine.py:365) which is the `KalshiFeed` WebSocket
  (engine.py:351; subscribes ticker/orderbook_delta/trade at kalshi_feed.py:150). The 30s
  candle poller (engine.py:342-348) only feeds the *chart* (`self.candles`, used at :413),
  NOT decisions. So the 2s eval (engine.py:422) is the genuine steady-state reaction time
  to a price/flow move. The honest caveat is the WS reconnect gap (5s backoff,
  kalshi_feed.py:135) during which the snapshot is stale and `connected=False`.
- **The LIVE path does NOT inherit the C1 stale-price bug.** In `make_context` with
  `is_replay=False`, the price is aligned to the model's own timestamp via
  `_price_at(history, model_ts)` (engine.py:166) and staleness is tracked as `model_age_s`
  (engine.py:169). This is the correct treatment; the C1 leak was a backtest-only artifact.
- **The "latency doesn't matter" claim is the one wrong thing here.** It conflates "no edge
  in the model-market gap" (true — see Claim 3, every strategy net-negative) with "no edge
  that is latency-sensitive." Those are different. The team has explicitly *pivoted to
  microstructure* (commit acedbfe, research/edge_discovery.py). A microstructure/order-flow
  edge — reacting to a large print or a book imbalance before the price catches up — is
  PRECISELY the kind of edge whose entire P&L lives in the first few seconds. A 2s eval +
  a 5s WS-reconnect-gap exposure on a shared e2-micro that is also doing git I/O is a
  plausible edge-killer for the exact strategy class being chased. So "latency doesn't
  matter" is true for the dead strategy and false for the live thesis. This deserves a
  flag, not a footnote.

Severity: the latency claim is a strategic mis-statement (it could cause the team to NOT
measure the one thing that gates the microstructure pivot). The rest of Claim 2 is sound.

## CLAIM 3 — "The data is complete and model-ready." → **OVERCLAIMED**

Completeness: **upheld and honest.** Reproduced across all 246 corpus games:
- candles(>5 bars) 246/246, plays 246/246, win_prob 246/246 (100%, as claimed).
- **Official Kalshi settlement 240/246 = 97.6%**, 6 absent (aged out) — exactly the "97%,
  6 aged out" claim. (My first scan read the wrong key path and reported 0%; I re-ran with
  the correct `rec['data']['kalshi_result']` path — **objection withdrawn**, the claim is
  correct and `backfill_results` (historical.py:234) did run, commit 02e17ce.)
- **ESPN-fallback "verified to agree" reproduced: 240/240 agree, 0 disagreements.** The
  cross-check in historical.py:257-264 is real and passes on this corpus.
- Trade-tape truncation fix verified: `FLOW_MAX_PAGES = 400` and it now *logs* when hit
  (historical.py:135,193) — was 80 pages, silently truncated busy games. Correct fix.
- WNBA gap verified and material: corpus leagues = `{'NBA': 246}`, zero WNBA, while
  `data/games/` shows live WNBA paper-trading in progress (e.g. 20260525_WNBA_CONN_GS,
  four WNBA captures dated 20260527). You are forward-testing a league you have zero
  backtest coverage for.

"Model-ready" is where it's oversold:
- **The corpus has so far demonstrated NO edge, not readiness to train one.** Full
  backtest (post-C1) on all 246 games: every single strategy is net-negative —
  `edge_naive -$10.45/g`, `wp_momentum -$5.99/g`, `model_revert -$3.93/g`, best is
  `late_fav -$0.12/g`, `spread_cap` trades 0×. The C1 finding (edge_naive +$11.82 → deeply
  negative) reproduces. That's a *correct and valuable* result, but it means the dataset's
  current verdict is "no signal in these features," which is the opposite of "model-ready."
- **n=246, one league, one ~2-month season slice, with heavy within-game autocorrelation**
  (hundreds of per-play decisions per game are not independent samples). For finding AND
  validating a durable, fee-surviving edge, the effective independent-sample count is closer
  to ~246 game-outcomes, not the thousands of trades. That is underpowered to confirm a
  small microstructure edge out-of-sample (the team's own metrics.py:73 targets ~100 OOS
  bets — a bar not yet met).
- **The new microstructure features (n_trades, max_trade, large-print vol ≥500 at 30s
  buckets, historical.py:131) are a reasonable first guess, not validated predictors.** No
  evidence yet that 30s aggregation or a 500-contract "large" threshold is the right
  resolution/cutoff for an informed-flow signal; calling them microstructure features is
  fine, implying they're the *right* ones is premature.
- **Mild survivorship/recency bias** in corpus construction: only `settled`/`finalized`
  markets (historical.py:38) that STILL have retrievable candles (≤5 bars dropped,
  historical.py:94) enter the corpus. Voided/suspended games and games whose candles aged
  out of Kalshi's ~2-month window are silently excluded. Small for binary game markets that
  nearly always settle, but real and uncaveated.

Severity: completeness claims cost nothing (they're accurate). "Model-ready" costs
*iteration direction* — it risks treating an underpowered, single-league, no-edge-yet
corpus as a trustworthy training/validation base.

## CLAIM 4 — "We cleaned up properly as we iterated." → **UPHELD**

All four fixes are present AND the reasoning is sound (not just "present in code"):
- **C1 (fill_candle look-ahead):** `engine.py:593-602` fills at the first bar whose
  `ts` > t. Candle `ts` = `end_period_ts` (engine.py:106) and the interval is **60s**
  (measured: mode 60s over 157 gaps). So the fill is the *contemporaneous* bar containing
  the play, struck at its close — a median **32s** (max 60s, p90 55s) after the play
  (measured over 525 plays). The fix's own comment ("first bar that closes after t … up to
  ~60s") is accurate. **The "new forward bias" attack is real but minor and in the SAFE
  direction:** filling at the bar close means you pay any intrabar drift that already priced
  the play — measured mean |close−open| = 1.85¢ (p90 5¢). That makes the backtest slightly
  *pessimistic*, which is the correct way to be wrong for an anti-look-ahead fix. A more
  precise fix would model reaction latency explicitly (fill at signal_ts + Δ via the bar
  open or interpolation); the close is a defensible conservative choice, not a bug.
- **C2 (backfill official results):** ran, 240/246 populated, cross-check passes (above).
- **C3 (FIFO deque dedup):** `tradelog.py:18,112-135` — `set` for membership + `deque` for
  true-FIFO eviction of the oldest key. Correct; fixes the old set-slice bug.
- **C4 (.gitattributes scoping + push-gate):** `.gitattributes` scopes `merge=union` to
  `data/**/*.jsonl` only, forces `merge=text` on meta.json/strategy_params.json/docs, and
  marks `*.gz binary` (protects the corpus). `deploy/git_sync.sh:13-36` removed global
  `-X union` and added a JSON-parse push-gate that refuses to push corrupt single-object
  JSON. Genuinely safer.
- **trades.jsonl untracked:** gitignored (`.gitignore:16`), 0 tracked in index. **One real
  consequence:** `shards.py:132` reads `trades.jsonl` for the last-15-trades strip. On the
  VM (which writes it live) shards are fine; on any OTHER clone the strip renders empty
  since the file isn't pulled. Cosmetic degradation off-VM, not data loss (tape re-fetchable,
  as the .gitignore comment notes). No regression to shard *regeneration* of candles/ticks.

No fix introduced a correctness regression that I could find.

Severity: footnote. The cleanup is above-average rigor for a solo lab.

---

## The single most important thing Claude is wrong about / underrates

**The "latency doesn't matter" claim (Claim 2), against the microstructure pivot (Claim 3).**
Evidence: every strategy is net-negative in the 246-game backtest (no edge in the
model-market gap — measured), AND the team has pivoted to structural/microstructure
(commit acedbfe, edge_discovery.py, the new n_trades/max_trade/large-print features). A
microstructure edge is latency-sensitive *by definition* — its P&L is the move you capture
before the price catches up. So "latency doesn't matter" is true only for the strategy that
just died and false for the strategy class being chased. Concretely, the live loop's 2s
eval + 5s WS-reconnect-gap + git I/O on a shared e2-micro is exactly the budget that gates
a fast order-flow edge, and it is currently *unmeasured*. Claude should be measuring
tick-to-decision-to-(paper)fill latency on the live path, not declaring it irrelevant.

## What Claude got RIGHT that I tried to knock down and couldn't

1. **The 0.28s no-re-sim board push** — measured 0.30s, and `compute_stats` provably reads
   the ledger snapshot, not a fresh simulation. Honest.
2. **Settlement 97% + ESPN agreement** — I scanned, got 0% on a wrong key path, suspected a
   false claim; re-ran correctly and got 240/246 (97.6%) and 240/240 agreement. The claim is
   exactly right. (Objection withdrawn.)
3. **The C1 fix does not introduce a meaningful new look-ahead** — I expected a ~60–120s
   forward-bias hole; the end-ts candle semantics make it the contemporaneous bar, median
   32s, and the residual bias is ~1–2¢ in the *conservative* direction. The fix is correct.
4. **All C1–C4 fixes are present and well-reasoned**, including the often-skipped details
   (binary .gz merge guard, JSON push-gate, true-FIFO eviction). Real cleanup, not theater.
