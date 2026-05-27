# LAB REVIEW — outside quant-infra audit (2026-05-27)

## Executive summary
The lab's *discovery* layer (`research/edge_discovery.py`) is rigorous and correctly
concludes there is no predictive edge in the model–market gap. But the *backtest/board*
layer it feeds the founder is not: `engine.simulate` compares a fresh ESPN win-prob to a
price candle that is **~50s stale on average (median 36s)** with **no freshness guard and
no `model_age_s` penalty**, so the same gap-trading strategies that EDGE_SCAN kills show
large fake profits (conviction +$5.22/game, the "do-not-trust" `edge_naive` control
+$11.82/game over 246 games). Those leaky numbers are exactly what `boards.py` publishes as
strategy performance. Separately, the corpus has silent integrity gaps (`kalshi_result=None`
for all 246 games; corpus is 100% NBA despite multi-league code/capture), the live-capture
trade tape has a dedup bug that bloated one game's `trades.jsonl` to 8 MB / 110k lines
committed 411× (a large share of the 135 MB pack), and the `-X union` git merge is a latent
corruption hazard for the rewritten JSON files. Fixing the freshness leak in the backtest
path is the single highest-leverage change — without it every board number and every
"backtest vs live agree" claim is comparing noise to a leak.

Findings: **🔴 CRITICAL 4 · 🟠 SIGNIFICANT 5 · 🟡 POSITIONING 4 · ⚪ MINOR 3**

---

## 🔴 CRITICAL — silent correctness / data-integrity

### C1. Backtest sim has look-ahead via stale prices; no freshness guard (the board's edge is an artifact)
- **Where:** `engine.simulate` (engine.py:560–635); `make_context` replay branch
  (engine.py:159–169 sets `aligned = implied`, `age = 0.0`); consumed by
  `backtest.run_suite` → `record_suite` → `boards.py`.
- **Evidence:** Measured candle staleness at each decision in a sample corpus game:
  **median 36s, mean 50s, 20% of decisions >60s stale** (candle `ts` = 1-min bar end,
  selected as last bar ending ≤ play wallclock; ESPN win-prob at that play already reflects
  the just-completed scoring play). In replay `model_age_s` is hard-coded to `0.0` and
  `aligned_implied` is just the stale mid — no penalty. **No strategy reads `model_age_s`**
  (`grep model_age strategies.py` → only the dataclass field/comment). Reproduced the
  resulting P&L over all 246 games: `conviction +$5.22/g`, `auto_house +$2.82/g`,
  `late_fav +$0.65/g`, and `edge_naive` — whose own docstring says it's "a latency-free
  artifact, NOT meant to be trusted" — **+$11.82/g on 29,191 trades**. Meanwhile
  `edge_discovery.py`, which *does* drop stale bars (`FRESH_S=90`, edge_discovery.py:46,212),
  and the calibration block (Kalshi Brier 0.1181 vs ESPN 0.1181, identical) correctly find
  no edge. The two sim paths disagree because only one guards freshness.
- **Impact:** Every "backtest $/g" on the public board and every "backtest vs live agree"
  claim is built on a model that peeks ~50s ahead of the tradeable price. This is the charter's
  exact "clutch artifact." It silently validates strategies that have no real edge and will
  mis-rank the whole roster.
- **Action (M):** Make `engine.simulate` enforce the same freshness contract as
  `edge_discovery`: compute real `model_age_s` from `play.wallclock − candle.ts`, and either
  (a) skip evaluation when the bar is staler than ~90s, or (b) compare the model to the
  *price as of the model's own timestamp*. Re-run the suite; expect the gap-trading P&L to
  collapse toward zero, matching EDGE_SCAN. Until then, label all board backtest numbers
  "leaky — provisional."

### C2. `kalshi_result` is `None` for the entire 246-game corpus; settlement silently falls back to ESPN
- **Where:** `historical.discover` / `_settled_index` (historical.py:35–79),
  `fetch_and_store` skip-on-exists (historical.py:88–89); fallback in
  `engine._settle_yes` (engine.py:69–77).
- **Evidence:** Scanned all 246 `data/backtest/*.json.gz` → `kalshi_result` distribution
  `{'None': 246}`. Yet the live API **does** return official results: probed corpus tickers —
  `20260406_NBA_PHI_SAS` and `20260524_NBA_OKC_SAS` both return `result='no'` live, but are
  stored as `None`. Root cause: games are stored before settlement (or `_settled_index`
  hadn't seen the result), and `fetch_and_store` returns `"skip"` whenever the file exists,
  so the official result is **never backfilled**. The oldest game (Mar 19) has now aged out
  of Kalshi entirely (`status=None`), so its truth is permanently unrecoverable from Kalshi.
- **Impact:** All corpus settlement currently runs on ESPN final score, not Kalshi's official
  result. Today these usually agree, but (a) there is no cross-check catching the cases where
  they don't (suspended/forfeited/corrected games, OT scoring edge cases), and (b) the
  authoritative ground truth is being discarded and aging out beyond recovery.
- **Action (S):** Add a `backfill_results()` pass (mirror `backfill_flow`) that re-opens each
  corpus file lacking a `yes/no` result and fills it from `engine.kalshi_result`; run it before
  games age out. Then have `_settle_yes` log/flag any ESPN-vs-Kalshi disagreement instead of
  silently preferring one.

### C3. Trade-tape dedup evicts the wrong keys → same trades re-appended; 8 MB/110k-line `trades.jsonl`
- **Where:** `tradelog.TradeTapeLogger.flush` (tradelog.py:113–125), specifically
  `self._seen = set(list(self._seen)[-2000:])`.
- **Evidence:** `data/games/20260526_NBA_SAS_OKC/trades.jsonl` is **8.0 MB, 110,063 lines**,
  and the records carry **no trade id** (keys: `price, count, taker_side, ts_ms`) so
  `unique-by-content` collapses to ~1. The dedup `_seen` set is bounded by slicing a **`set`**
  (unordered) to "last 2000" — `list(set)[-2000:]` keeps an *arbitrary* 2000 keys, not the
  most recent. Once a long game exceeds 5000 trades, evicted-but-still-valid keys re-appear as
  "new" and get re-written. README claims event-based logging keeps a game "~1–2 MB"; this one
  is 11 MB total.
- **Impact:** Massive file bloat (see S1 for the git multiplier). Analytic impact is limited
  *today* because the only consumer reads the last 15 lines (`shards.py:132`), but if the raw
  tape is ever used for flow the duplicates would double-count order flow.
- **Action (S):** Make `_seen` an `OrderedDict`/`deque`+`set` and evict in true FIFO order;
  or dedup on a real trade id if Kalshi provides one. Consider dropping the raw tape entirely
  in favor of the condensed per-30s flow buckets already built by `historical.fetch_flow`.

### C4. `-X union` git merge will corrupt rewritten JSON during VM↔local concurrency
- **Where:** `deploy/git_sync.sh` (`git pull --rebase --autostash -X union origin main`).
- **Evidence:** `union` concatenates both sides of a conflicting hunk. That is safe-ish for
  pure append-only JSONL, but several committed files are **fully rewritten in place**:
  every `data/games/*/meta.json` (`json.dump(meta, open(mp,"w"))` in engine.py:444 and
  deploy/finalize_game.py), `strategy_params.json`, and the `docs/*.md` boards. If the daemon
  and the local cycle rewrite the same one between fetch and push, union will produce two
  concatenated JSON objects = invalid JSON, or interleaved/duplicated markdown. Verified no
  corruption *yet* (all 21 meta.json + 5 ledgers parse, 0 unparseable, 0 exact-dupe lines) —
  this is **latent**, not yet triggered, because collisions have been rare and files small.
  Note also union can merge two JSONL lines into one (lost trailing newline) under the right
  conflict alignment.
- **Impact:** A single unlucky concurrent rewrite silently corrupts a meta.json (wrong P&L /
  settlement for that game) or `strategy_params.json` (which gates every strategy), and it
  rides through because nothing validates JSON post-merge.
- **Action (M):** Add a `.gitattributes` setting `merge=union` **only** for the truly
  append-only JSONL paths (`data/**/*.jsonl`) and force a normal/`ours-with-rebase` strategy
  for the rewritten single-object files; add a post-merge `python -c "json.load"` validation
  gate in `git_sync.sh` that aborts the push if any tracked `.json` fails to parse.

---

## 🟠 SIGNIFICANT — redundancy / inefficiency / cost

### S1. One game's growing 8 MB tape re-committed 411× → most of the 135 MB pack
- **Where:** daemon push cadence (run_paper.py:133–148, pushes every ~5 min while live) ×
  append-only `trades.jsonl` (C3).
- **Evidence:** `git log --follow data/games/20260526_NBA_SAS_OKC/trades.jsonl` → **411
  commits**; the blob appears in history at 6.5–8.4 MB across many of them. `.git` is 178 MB,
  pack 135 MB; `data/` on disk is only 43 MB. The largest 15 history blobs are *all* that one
  trades.jsonl. Each 5-min push re-stores the whole grown file (git can't delta a file that
  changes throughout).
- **Impact:** Repo is ~4× larger than its live data; every `git pull` on the e2-micro and
  every Pages deploy drags the bloat. Compounds with C3 (the file is bloated *and* re-committed).
- **Action (M):** Fix C3 to shrink the file; reduce push frequency for high-write per-game
  streams or `.gitignore` the raw `trades.jsonl` (keep only the condensed flow buckets, which
  are what backtests actually consume); one-time history rewrite (`git filter-repo`) to reclaim
  the pack. This is the parked Postgres trigger — but the cheap win is "don't commit the raw
  tape," not a DB migration.

### S2. Corpus is 100% NBA despite multi-league code and active WNBA capture
- **Where:** `historical.build` iterates `LEAGUES` (historical.py:107–128); capture daemon is
  clearly running WNBA (`data/games/20260527_WNBA_*`).
- **Evidence:** All 246 corpus games are NBA (`leagues: {'NBA': 246}`); EDGE_SCAN header says
  "246 games (NBA)". Live captures include numerous WNBA games. So the durable backtest corpus
  the lab reasons over excludes an entire league it's actively trading on paper.
- **Impact:** Every backtest/calibration conclusion is NBA-only; WNBA strategies are
  effectively un-backtested, and the single-league concentration the charter flags as a risk
  is worse than it looks. Likely `historical.discover` isn't matching WNBA (ESPN abbr / sport
  path) — unverified root cause, needs check.
- **Action (S):** Run `historical.py --leagues KXWNBAGAME` and inspect the `discover` tally;
  fix the ESPN-match/`espn_abbr` path for WNBA so the corpus covers what's being traded.

### S3. Two divergent sim paths that can silently disagree
- **Where:** `engine.simulate` (replay corpus) vs `engine.simulate_captured` (live ticks) vs
  the strategies' own live loop in `LiveEngine.run`.
- **Evidence:** `simulate` injects per-30s flow from `data["flow"]` and uses
  `is_replay=True` (age=0, aligned=implied); `simulate_captured` replays real ticks with
  `is_replay=False` and real `history`/`now_ts`; the live loop uses yet another freshness/flow
  reality. The freshness leak (C1) lives in `simulate` but **not** in `simulate_captured`, so
  the same strategy can score very differently across the two backtests with no reconciliation.
  `backtest.py` lists a hand-maintained `REPLAYABLE` subset that already drifts from
  `analyze.py`, which runs the *full* `REGISTRY` through `run_suite` (order-flow strategies
  included, where flow is only the coarse 30s bucket) — backtest.py:197 vs analyze.py:92.
- **Impact:** "Backtest agrees with live" can be two different engines agreeing by luck;
  maintenance edits to one path don't propagate to the other.
- **Action (M):** Unify on one context-construction + freshness contract shared by all three
  entry points; assert the corpus-replay and captured-replay agree on the overlap set of games.

### S4. `analyze.py` re-simulates the full 246-game corpus every cycle
- **Where:** `analyze.py:91–96` (`load_all` + `run_suite` over full REGISTRY + `run_captured`).
- **Evidence:** `run_suite` calls `engine.simulate` for every game × every strategy each run;
  reproducing just 4 strategies over 246 games took the full call. The corpus changes only when
  `historical.py` adds games, but the suite re-runs unconditionally each cycle. (Good news:
  `boards.py` does **not** re-simulate — it reads the ledger snapshot — so the hot push path is
  fine; the cost is only in the daily cycle.)
- **Impact:** Wasted compute/credits each cycle re-deriving identical numbers when neither the
  corpus nor `strategy_params.json` changed.
- **Action (S):** Cache `run_suite` keyed by `(corpus hash, params_version)`; skip if unchanged.

### S5. `record_suite` appends a fresh full snapshot to the ledger every cycle
- **Where:** `backtest.record_suite` (backtest.py:159–173) → `data/results/strategy_history.jsonl`.
- **Evidence:** 38 backtest rows already (5× `backtest-69games`, 33× `backtest-246games`),
  one set per cycle/params bump. Append-only; the board takes the latest per strategy.
- **Impact:** Minor now (74 lines total) but unbounded growth of a file that only ever needs
  the latest-per-(strategy,params); compounds the union-merge surface (C4).
- **Action (S):** Either keep an explicit time series on purpose, or upsert latest-per-key.

---

## 🟡 POSITIONING — high-leverage, scrappy

### P1. Trust the discovery layer; demote the leaky backtest board
- The lab already *has* the rigorous answer (EDGE_SCAN: no predictive edge; survivors table
  empty/marginal). The board contradicts it with leaky P&L (C1). Make EDGE_SCAN's
  freshness-guarded, game-clustered, OOS-split methodology the **single source of truth** for
  "does this strategy have an edge," and relabel `boards.py` numbers as engine-sanity output,
  not edge evidence. Cheap, prevents self-deception. (S)

### P2. The honest next edge is structural — instrument fee/settlement and favorite-longshot directly
- Calibration confirms ESPN ≈ Kalshi (Brier tie), so per the charter the only durable edge is
  structural. You already pay zero fee at settlement; the cheapest high-value instrumentation is
  a **directly-measured favorite-longshot bias** table from the corpus (realized win-rate vs
  price by band — the 0.0–0.1 band already shows realized 0.015–0.031 vs priced ~0.033, i.e.
  longshots slightly *over*priced) and a **spread/round-trip-cost** ledger from the captured
  tape. Both are read-only over data you have. (M)

### P3. Capture must reliably persist the final score
- `20260522_OKC_SAS` finalized with `kalshi_result=yes` but `final_score={away:None,home:None}`
  (verified in meta.json). A settled game with no score can't be ESPN-cross-checked and is
  useless for margin-regime analysis. Harden `_save_meta`/`finalize_game` to require a non-null
  score (fall back to last tick's score, which is already available). (S)

### P4. Two-anchor calibration (de-vig sportsbook) is the cheapest way to break the ESPN/Kalshi tie
- With ESPN and Kalshi calibrated identically, you have no second opinion. A free de-vig
  sportsbook line (already noted as "later" in the charter) is the highest-leverage *new* data
  source — it's the only way to find where the market is wrong without out-predicting it. (M)

---

## ⚪ MINOR

### M1. `edge_discovery.main()` runs each mispricing scan twice
- edge_discovery.py:276–279: `mispricing_scan(disc,...)` and `(hold,...)` are each called once
  to grab `rows` (return value discarded with `_,`) and again to grab the markdown lines. Four
  scans where two suffice. Cheap to fix: keep both return values from one call. (S) — confirmed,
  as the prompt flagged.

### M2. Pre-game flow buckets injected into early-game decisions (small leak)
- In a sampled game, **77% of flow buckets end before the first price candle** (the tape spans
  ~55h before tip-off). `engine.simulate` (line 608) selects the latest bucket ending ≤ play
  time, so the *first* few in-game plays can be tagged with a pre-game flow bucket until an
  in-game bucket forms. Buckets are dense (every 30s) right up to tip-off, so the practical
  contamination is a handful of early plays per game — low severity, but flow-based signals near
  game start are reading stale/pre-game order flow. Action: clamp `flow` to `t ≥ first_candle_ts`. (S)

### M3. Old/new game_id naming coexist; possible duplicate-matchup captures
- `data/games/` mixes legacy `20260522_OKC_SAS` (no league prefix) with new
  `20260526_NBA_SAS_OKC`. Several recent dirs are `status=pre/None, score=None` (incomplete
  captures from daemon restarts). Not corrupting analysis (finalize/skip logic handles
  `final_status`), but clutters the corpus and the board's recent-games list. Action: a sweep
  with `finalize_game.py --all` plus a one-time rename of legacy ids. (S)

---

_Method note: all 🔴/🟠 findings were verified by reading the cited code and running read-only
checks against the real corpus (246 gz files), captured games, git history, and the live Kalshi
API. Items marked "unverified — needs check": S2 root cause (WNBA match failure) and the exact
trigger conditions for C4 (no corruption observed yet, hazard is structural)._
