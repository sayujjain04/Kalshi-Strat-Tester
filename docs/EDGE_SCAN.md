# EDGE SCAN — mining the corpus for real, OOS-validated edge

_`research/edge_discovery.py`. 24,135 play observations across **57 games** (WNBA) (23,301 with a fresh ≤90s price bar). Time-split: discovery = first 60% of games, holdout = games from 20260517 on._

> Charter read-order: disconfirmation first. The market is the prior; a model 'edge' is guilty until it survives the holdout, clears fees, and has enough games behind it.

### Calibration — ALL  (n=24,135 plays)
- **Brier (lower=sharper): Kalshi mid 0.1712  ·  ESPN WP 0.1758** → MARKET sharper by 0.0046

| pred band | n | realized | mkt mean | espn mean |
|---|---|---|---|---|
| 0.0–0.1 | 2,851 | 0.013 | 0.034 | 0.034 |
| 0.1–0.2 | 1,560 | 0.150 | 0.144 | 0.150 |
| 0.2–0.3 | 1,996 | 0.463 | 0.243 | 0.249 |
| 0.3–0.4 | 2,522 | 0.531 | 0.348 | 0.352 |
| 0.4–0.5 | 2,331 | 0.457 | 0.444 | 0.446 |
| 0.5–0.6 | 1,921 | 0.594 | 0.546 | 0.550 |
| 0.6–0.7 | 2,227 | 0.614 | 0.645 | 0.647 |
| 0.7–0.8 | 2,184 | 0.634 | 0.745 | 0.752 |
| 0.8–0.9 | 2,366 | 0.835 | 0.844 | 0.850 |
| 0.9–1.0 | 4,177 | 0.956 | 0.965 | 0.968 |

### Calibration — HOLDOUT only  (n=9,575 plays)
- **Brier (lower=sharper): Kalshi mid 0.1721  ·  ESPN WP 0.1787** → MARKET sharper by 0.0065

| pred band | n | realized | mkt mean | espn mean |
|---|---|---|---|---|
| 0.0–0.1 | 1,000 | 0.037 | 0.036 | 0.039 |
| 0.1–0.2 | 624 | 0.093 | 0.141 | 0.149 |
| 0.2–0.3 | 751 | 0.546 | 0.246 | 0.252 |
| 0.3–0.4 | 990 | 0.507 | 0.346 | 0.351 |
| 0.4–0.5 | 1,050 | 0.447 | 0.446 | 0.447 |
| 0.5–0.6 | 850 | 0.476 | 0.547 | 0.546 |
| 0.6–0.7 | 801 | 0.509 | 0.644 | 0.650 |
| 0.7–0.8 | 772 | 0.509 | 0.744 | 0.750 |
| 0.8–0.9 | 816 | 0.882 | 0.843 | 0.851 |
| 0.9–1.0 | 1,921 | 0.986 | 0.968 | 0.972 |

## Mispricing — discovery vs holdout

### Mispricing scan — DISCOVERY (first 60% of games)
Net ¢ = realized settlement − ask/bid you'd cross − fee, **averaged across games** (the real unit; cells need ≥12 games and a fresh price bar ≤90s). Positive net = candidate edge.

| time | gap (model−mid) | games | net ¢ | game-win% |
|---|---|---|---|---|
| 3_late(2-10m) | +10-18c | 18 | **+12.2** | 61% |
| 4_clutch(<2m) | -10-18c | 12 | **+8.5** | 50% |
| 3_late(2-10m) | +6-10c | 23 | **+6.3** | 61% |
| 2_mid(10-30m) | +6-10c | 27 | **+5.6** | 63% |
| 1_early(>30m) | +3-6c | 26 | **+5.6** | 58% |
| 2_mid(10-30m) | +10-18c | 19 | **+4.6** | 58% |
| 4_clutch(<2m) | +3-6c | 13 | **+4.2** | 62% |
| 3_late(2-10m) | +3-6c | 26 | **+3.3** | 62% |
| 2_mid(10-30m) | +3-6c | 31 | **-0.7** | 58% |
| 4_clutch(<2m) | -3-6c | 15 | **-1.5** | 33% |
| 2_mid(10-30m) | -18c+ | 12 | **-2.8** | 42% |
| 4_clutch(<2m) | -6-10c | 15 | **-3.3** | 40% |
| 3_late(2-10m) | -10-18c | 20 | **-4.8** | 50% |
| 1_early(>30m) | +6-10c | 17 | **-7.3** | 41% |
| 1_early(>30m) | -10-18c | 24 | **-7.6** | 42% |
| 3_late(2-10m) | -6-10c | 22 | **-8.0** | 45% |
| 3_late(2-10m) | -3-6c | 27 | **-8.3** | 44% |
| 2_mid(10-30m) | -10-18c | 26 | **-9.1** | 42% |
| 2_mid(10-30m) | -3-6c | 32 | **-9.7** | 41% |
| 1_early(>30m) | -3-6c | 27 | **-10.3** | 41% |
| 2_mid(10-30m) | -6-10c | 27 | **-10.5** | 44% |
| 1_early(>30m) | -6-10c | 27 | **-10.8** | 41% |

### Mispricing scan — HOLDOUT (later 40% of games)
Net ¢ = realized settlement − ask/bid you'd cross − fee, **averaged across games** (the real unit; cells need ≥12 games and a fresh price bar ≤90s). Positive net = candidate edge.

| time | gap (model−mid) | games | net ¢ | game-win% |
|---|---|---|---|---|
| 1_early(>30m) | +10-18c | 14 | **+7.6** | 64% |
| 2_mid(10-30m) | +10-18c | 17 | **+6.9** | 65% |
| 3_late(2-10m) | -6-10c | 12 | **+4.9** | 67% |
| 2_mid(10-30m) | +6-10c | 18 | **+4.4** | 67% |
| 3_late(2-10m) | -10-18c | 12 | **+3.8** | 67% |
| 1_early(>30m) | +6-10c | 17 | **+1.9** | 59% |
| 3_late(2-10m) | +10-18c | 13 | **+1.6** | 54% |
| 3_late(2-10m) | +6-10c | 14 | **+1.2** | 50% |
| 2_mid(10-30m) | -10-18c | 12 | **+0.8** | 58% |
| 2_mid(10-30m) | +3-6c | 21 | **-0.0** | 62% |
| 3_late(2-10m) | -3-6c | 14 | **-0.3** | 57% |
| 1_early(>30m) | +3-6c | 20 | **-2.5** | 55% |
| 3_late(2-10m) | +3-6c | 16 | **-2.7** | 50% |
| 2_mid(10-30m) | -6-10c | 15 | **-3.6** | 53% |
| 1_early(>30m) | -3-6c | 14 | **-4.2** | 50% |
| 1_early(>30m) | -6-10c | 13 | **-7.4** | 46% |
| 2_mid(10-30m) | -3-6c | 18 | **-9.0** | 50% |

### Survivors — positive net edge in BOTH halves (the only cells worth a strategy)

| time | gap | disc net ¢ | disc games | hold net ¢ | hold games |
|---|---|---|---|---|---|
| 3_late(2-10m) | +10-18c | +12.2 | 18 | +1.6 | 13 |
| 3_late(2-10m) | +6-10c | +6.3 | 23 | +1.2 | 14 |
| 2_mid(10-30m) | +6-10c | +5.6 | 27 | +4.4 | 18 |
| 2_mid(10-30m) | +10-18c | +4.6 | 19 | +6.9 | 17 |

