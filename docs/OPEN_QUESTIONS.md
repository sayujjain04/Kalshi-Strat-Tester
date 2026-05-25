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

## Closed

- **(2026-05-25) Load the local research schedule** — DONE. launchd agent
  `com.kalshi.research` is loaded and verified (ran a full iteration end-to-end). It
  runs the loop from `~/kalshi-lab` daily at 10:00 local (macOS blocks launchd from
  `~/Documents`, so the automation lives in `~/kalshi-lab`).
- **(2026-05-25) Anthropic API key** — not needed. Pivoted the research loop to run
  locally on the Mac via the Max-plan `claude` login instead of a metered API key on
  CI. Removed the CI workflow and deleted the Kalshi keys from GitHub Actions secrets.
