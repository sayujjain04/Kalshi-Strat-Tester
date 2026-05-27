# LEAD-LAG — EXP-009: is there a tradeable live intra-game lag?

_`research/lead_lag.py`. 2 captured games, per-second grid of Kalshi mid vs ESPN win-prob (both yes-space). Cross-corr of changes: lag>0 ⇒ price moves AFTER win-prob (a window for us); lag<0 ⇒ price LEADS our signal (we can't catch it)._

## Cross-correlation: corr(Δwin-prob[t], Δmid[t+lag])
| lag (s) | corr |
|---|---|
| -8 | +0.023 |
| -7 | -0.002 |
| -6 | +0.010 |
| -5 | -0.000 |
| -4 | +0.014 |
| -3 | -0.000 |
| -2 | +0.002 |
| -1 | -0.000 |
| +0 | +0.014 |
| +1 | -0.000 |
| +2 | -0.013 |
| +3 | -0.000 |
| +4 | -0.014 |
| +5 | -0.000 |
| +6 | -0.012 |
| +7 | -0.000 |
| +8 | -0.023 |

**Peak correlation at lag = -8s (price leads/coincident — no exploitable window for us).**

## Event study — avg signed mid move around 41 win-prob jumps (≥3¢)
_second 0 = the win-prob jump; values = cumulative mid move in the jump's direction (¢). If the price already moved by second 0, it leads us._

| sec rel to wp jump | -5 | -2 | 0 | +1 | +2 | +5 | +10 |
|---|---|---|---|---|---|---|---|
| cum mid move ¢ | -0.1 | +0.0 | +0.1 | +0.1 | +0.1 | +0.0 | +0.1 |

**By the jump (sec 0) the price has already moved +0.1¢; the additional move in the +2s we could act in is +0.0¢.** (Remember: we only LEARN of the jump via ESPN's ~5s poll — so even a positive +2s move isn't ours unless it persists past our signal+exec latency.)
