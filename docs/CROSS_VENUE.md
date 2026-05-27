# CROSS-VENUE — EXP-008 done right (Kalshi vs de-vig DraftKings)

_`research/cross_venue.py`. 294 games with a DK line (free via ESPN pickcenter). One independent pre-game bet per game (tip-off price vs DK closing line). Reported as expectancy / win-rate / win-vs-loss size — a small REAL +EV is scalable._

## Is either side sharper?
- **Brier: Kalshi 0.1928 · de-vig DK 0.1929** → Kalshi sharper by 0.0001
- |Kalshi − DK| divergence: mean 1.2¢ · median 1.1¢ · max 4.0¢ · >5¢ in 0/294 games

## Strategy: bet Kalshi toward the book when they diverge (hold to settlement)
| min divergence | bets | expectancy/bet | win% | avg win | avg loss | worst | total |
|---|---|---|---|---|---|---|---|
| ≥0¢ | 294 | **-0.04¢** | 37% | +51.7¢ | -30.1¢ | -84.9¢ | -12¢ |
| ≥2¢ | 56 | **-8.76¢** | 12% | +70.3¢ | -20.0¢ | -78.2¢ | -491¢ |
| ≥3¢ | 12 | **+0.27¢** | 17% | +77.9¢ | -15.3¢ | -49.7¢ | +3¢ |

## OOS (≥2¢ divergence, time-split)
- discovery: -12.06¢/bet over 42 bets (5% win)
- holdout:   +1.12¢/bet over 14 bets (36% win)
