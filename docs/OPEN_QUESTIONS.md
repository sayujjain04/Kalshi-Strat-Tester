# Open Questions & Escalations

The quant lead (Claude) decides everything about data, strategies, and experiments
**autonomously**. This doc is *only* for things the lead genuinely cannot do itself —
access, accounts, money, an external key, a human judgment call. The lead appends an
item, then **moves on to other work — it never blocks waiting on a reply.** When the
founder resolves an item, it moves to **Closed** with the resolution.

Founder: skim **Open**. Each item says exactly what to do and what it unblocks.

---

## Open

- _(none — nothing needs you right now)_

## Parked / planned (not blocking — revisit when the trigger hits)

- **(2026-05-26) Move the high-write data to Postgres (hybrid with git).** Today
  everything lives in git/GitHub (code + data + board), which doubles as version
  control + deploy + free Pages hosting + full reproducibility — good, and fine at our
  current scale. But it has costs we've felt: **concurrent-writer merge conflicts** (VM
  daemon + local loop + interactive sessions all push), **no real-time** (board is a
  static page on a ~5-min/Pages-capped refresh), **no SQL querying**, and **repo bloat**
  as tick volume grows.
  - **Plan:** keep git for code/config/board; move the high-write streams
    (`ticks`/`trades`/`decisions`/`results`) to **Postgres** — Supabase *or* self-hosted
    on the VM. Kills the merge-conflict churn, enables a genuinely live board (Supabase
    realtime / SSE), enables proper analytics queries, scales past repo bloat.
  - **Cost note:** Supabase free tier **pauses after ~1 week inactivity** (bad for an
    always-on lab) + **500 MB cap** (ticks fill it) → realistically ~$25/mo, or
    self-host Postgres on the e2-micro (free, more setup). Founder weighs cost/approach.
  - **Trigger to revisit:** when (a) git merge conflicts keep biting, or (b) tick data
    starts bloating/slowing clones. Until then: parked.

## Closed

- **(2026-05-25) Load the local research schedule** — DONE. launchd agent
  `com.kalshi.research` is loaded and verified (ran a full iteration end-to-end). It
  runs the loop from `~/kalshi-lab` daily at 10:00 local (macOS blocks launchd from
  `~/Documents`, so the automation lives in `~/kalshi-lab`).
- **(2026-05-25) Anthropic API key** — not needed. Pivoted the research loop to run
  locally on the Mac via the Max-plan `claude` login instead of a metered API key on
  CI. Removed the CI workflow and deleted the Kalshi keys from GitHub Actions secrets.
