# Open Questions & Escalations

The quant lead (Claude) decides everything about data, strategies, and experiments
**autonomously**. This doc is *only* for things the lead genuinely cannot do itself —
access, accounts, money, an external key, a human judgment call. The lead appends an
item, then **moves on to other work — it never blocks waiting on a reply.** When the
founder resolves an item, it moves to **Closed** with the resolution.

Founder: skim **Open**. Each item says exactly what to do and what it unblocks.

---

## Open

- [ ] **(2026-05-25) Load the local research schedule (one-time, ~5 sec).**
  The research loop now runs LOCALLY on your Mac using your Max-plan `claude` login
  (no API key, no metered billing). To schedule it daily, run:
  `cp deploy/com.kalshi.research.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.kalshi.research.plist`
  (Claude will try to do this for you; this item is here in case it needs your shell.)
  Unblocks: nightly autonomous iteration. You can always run one now with
  `bash deploy/research_local.sh`.

## Closed

- **(2026-05-25) Anthropic API key** — not needed. Pivoted the research loop to run
  locally on the Mac via the Max-plan `claude` login instead of a metered API key on
  CI. Removed the CI workflow and deleted the Kalshi keys from GitHub Actions secrets.
