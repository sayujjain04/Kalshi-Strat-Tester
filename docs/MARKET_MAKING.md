# MARKET MAKING — EXP-010: does passive spread capture pay?

_`research/market_making.py`. Captured games; for each taker fill WE are the maker on the other side. realized spread = half-spread earned − adverse selection (mid move against us over Δ); net = realized − maker fee. Contract-weighted. >0 net = scalable._

- Median quoted spread (ask−bid): **1.0¢** — the most a maker at the touch could gross per round-trip before adverse selection + fees.

| hold Δ | fills | contracts | realized spread ¢ | maker fee ¢ | **net ¢/contract** | % fills net+ |
|---|---|---|---|---|---|---|
| 30s | 214,801 | 60,393,412 | +0.35 | 1.13 | **-0.78** | 26% |
| 60s | 214,801 | 60,393,412 | +0.29 | 1.13 | **-0.84** | 28% |

**Verdict: Net **-0.78¢/contract** — NEGATIVE. Adverse selection + the maker fee (1.13¢) exceed the realized spread; passive MM loses on this market. (Kalshi's per-fill fee vs a ~1-2¢ spread is the likely killer.)**
