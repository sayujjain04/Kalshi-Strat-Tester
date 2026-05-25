# Open Questions & Escalations

The quant lead (Claude) decides everything about data, strategies, and experiments
**autonomously**. This doc is *only* for things the lead genuinely cannot do itself —
access, accounts, money, an external key, a human judgment call. The lead appends an
item, then **moves on to other work — it never blocks waiting on a reply.** When the
founder resolves an item, it moves to **Closed** with the resolution.

Founder: skim **Open**. Each item says exactly what to do and what it unblocks.

---

## Open

- [ ] **(2026-05-25) Anthropic API key for the headless research loop.**
  What to do: GitHub → the `Kalshi-Strat-Tester` repo → **Settings → Secrets and
  variables → Actions → New repository secret** → name it **`ANTHROPIC_API_KEY`**,
  paste your key. Optionally also add `MONTHLY_BUDGET_USD` (default 25) to cap spend.
  Unblocks: the nightly autonomous research iteration (`.github/workflows/research.yml`).
  Until it's set, the workflow runs but skips the model step.

## Closed

- _(none yet)_
