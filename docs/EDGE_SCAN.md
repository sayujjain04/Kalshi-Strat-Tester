# EDGE SCAN — mining the corpus for real, OOS-validated edge

_`research/edge_discovery.py`. 118,107 play observations across **246 games** (NBA) (115,222 with a fresh ≤90s price bar). Time-split: discovery = first 60% of games, holdout = games from 20260410 on._

> Charter read-order: disconfirmation first. The market is the prior; a model 'edge' is guilty until it survives the holdout, clears fees, and has enough games behind it.

### Calibration — ALL  (n=118,107 plays)
- **Brier (lower=sharper): Kalshi mid 0.1181  ·  ESPN WP 0.1181** → MARKET sharper by 0.0000

| pred band | n | realized | mkt mean | espn mean |
|---|---|---|---|---|
| 0.0–0.1 | 23,212 | 0.015 | 0.033 | 0.026 |
| 0.1–0.2 | 10,416 | 0.120 | 0.142 | 0.150 |
| 0.2–0.3 | 8,922 | 0.241 | 0.243 | 0.249 |
| 0.3–0.4 | 8,569 | 0.326 | 0.345 | 0.349 |
| 0.4–0.5 | 7,941 | 0.285 | 0.444 | 0.450 |
| 0.5–0.6 | 7,944 | 0.505 | 0.546 | 0.549 |
| 0.6–0.7 | 9,252 | 0.658 | 0.646 | 0.649 |
| 0.7–0.8 | 9,136 | 0.783 | 0.744 | 0.751 |
| 0.8–0.9 | 8,746 | 0.835 | 0.846 | 0.851 |
| 0.9–1.0 | 23,969 | 0.984 | 0.967 | 0.972 |

### Calibration — HOLDOUT only  (n=48,005 plays)
- **Brier (lower=sharper): Kalshi mid 0.1464  ·  ESPN WP 0.1342** → ESPN WP sharper by 0.0122

| pred band | n | realized | mkt mean | espn mean |
|---|---|---|---|---|
| 0.0–0.1 | 8,562 | 0.031 | 0.032 | 0.027 |
| 0.1–0.2 | 4,547 | 0.153 | 0.141 | 0.152 |
| 0.2–0.3 | 4,378 | 0.261 | 0.247 | 0.249 |
| 0.3–0.4 | 4,008 | 0.311 | 0.345 | 0.349 |
| 0.4–0.5 | 3,352 | 0.185 | 0.443 | 0.447 |
| 0.5–0.6 | 3,144 | 0.339 | 0.547 | 0.548 |
| 0.6–0.7 | 4,052 | 0.495 | 0.649 | 0.649 |
| 0.7–0.8 | 4,134 | 0.691 | 0.743 | 0.753 |
| 0.8–0.9 | 3,686 | 0.762 | 0.844 | 0.851 |
| 0.9–1.0 | 8,142 | 0.967 | 0.964 | 0.970 |

## Mispricing — discovery vs holdout

### Mispricing scan — DISCOVERY (first 60% of games)
Net ¢ = realized settlement − ask/bid you'd cross − fee, **averaged across games** (the real unit; cells need ≥12 games and a fresh price bar ≤90s). Positive net = candidate edge.

| time | gap (model−mid) | games | net ¢ | game-win% |
|---|---|---|---|---|
| 4_clutch(<2m) | -18c+ | 23 | **+16.5** | 57% |
| 4_clutch(<2m) | +18c+ | 29 | **+11.5** | 55% |
| 4_clutch(<2m) | -10-18c | 33 | **+5.3** | 42% |
| 4_clutch(<2m) | -6-10c | 38 | **+5.1** | 47% |
| 4_clutch(<2m) | +10-18c | 32 | **+4.7** | 47% |
| 3_late(2-10m) | +6-10c | 60 | **+2.2** | 57% |
| 2_mid(10-30m) | +10-18c | 67 | **+2.0** | 52% |
| 4_clutch(<2m) | +3-6c | 45 | **+1.5** | 53% |
| 2_mid(10-30m) | +3-6c | 98 | **+1.3** | 51% |
| 3_late(2-10m) | +3-6c | 75 | **+1.3** | 60% |
| 4_clutch(<2m) | -3-6c | 47 | **+0.8** | 45% |
| 1_early(>30m) | +3-6c | 102 | **-0.4** | 42% |
| 3_late(2-10m) | +10-18c | 46 | **-0.6** | 48% |
| 2_mid(10-30m) | +6-10c | 85 | **-1.3** | 51% |
| 3_late(2-10m) | +18c+ | 31 | **-1.6** | 42% |
| 1_early(>30m) | +6-10c | 92 | **-1.8** | 39% |
| 3_late(2-10m) | -10-18c | 50 | **-2.6** | 48% |
| 1_early(>30m) | -18c+ | 32 | **-2.7** | 38% |
| 1_early(>30m) | +10-18c | 69 | **-3.9** | 36% |
| 4_clutch(<2m) | +6-10c | 32 | **-4.0** | 41% |
| 3_late(2-10m) | -3-6c | 76 | **-4.1** | 49% |
| 3_late(2-10m) | -18c+ | 27 | **-4.6** | 41% |
| 2_mid(10-30m) | -3-6c | 103 | **-5.0** | 49% |
| 2_mid(10-30m) | +18c+ | 36 | **-5.2** | 39% |
| 3_late(2-10m) | -6-10c | 63 | **-6.4** | 48% |
| 1_early(>30m) | -3-6c | 97 | **-7.0** | 35% |
| 2_mid(10-30m) | -6-10c | 82 | **-7.1** | 43% |
| 2_mid(10-30m) | -10-18c | 64 | **-7.5** | 41% |
| 1_early(>30m) | -6-10c | 90 | **-8.3** | 31% |
| 1_early(>30m) | +18c+ | 32 | **-9.1** | 28% |
| 2_mid(10-30m) | -18c+ | 38 | **-9.7** | 32% |
| 1_early(>30m) | -10-18c | 72 | **-11.4** | 29% |

### Mispricing scan — HOLDOUT (later 40% of games)
Net ¢ = realized settlement − ask/bid you'd cross − fee, **averaged across games** (the real unit; cells need ≥12 games and a fresh price bar ≤90s). Positive net = candidate edge.

| time | gap (model−mid) | games | net ¢ | game-win% |
|---|---|---|---|---|
| 3_late(2-10m) | -18c+ | 26 | **+24.0** | 77% |
| 2_mid(10-30m) | -18c+ | 33 | **+22.4** | 70% |
| 4_clutch(<2m) | -18c+ | 18 | **+20.4** | 50% |
| 1_early(>30m) | -18c+ | 32 | **+15.7** | 59% |
| 4_clutch(<2m) | +18c+ | 15 | **+13.0** | 60% |
| 1_early(>30m) | -10-18c | 66 | **+10.7** | 59% |
| 4_clutch(<2m) | -10-18c | 20 | **+10.6** | 45% |
| 2_mid(10-30m) | -10-18c | 57 | **+8.1** | 61% |
| 1_early(>30m) | -6-10c | 78 | **+7.1** | 58% |
| 2_mid(10-30m) | -6-10c | 68 | **+7.1** | 65% |
| 3_late(2-10m) | -10-18c | 44 | **+7.0** | 70% |
| 3_late(2-10m) | +10-18c | 33 | **+5.9** | 61% |
| 4_clutch(<2m) | +10-18c | 16 | **+4.9** | 50% |
| 4_clutch(<2m) | -6-10c | 27 | **+4.6** | 44% |
| 1_early(>30m) | -3-6c | 80 | **+4.3** | 52% |
| 4_clutch(<2m) | +3-6c | 30 | **+3.8** | 53% |
| 2_mid(10-30m) | -3-6c | 81 | **+3.6** | 60% |
| 1_early(>30m) | +18c+ | 13 | **+3.5** | 38% |
| 4_clutch(<2m) | -3-6c | 29 | **+3.2** | 48% |
| 3_late(2-10m) | +18c+ | 14 | **+3.0** | 64% |
| 1_early(>30m) | +10-18c | 35 | **+2.2** | 46% |
| 3_late(2-10m) | -6-10c | 50 | **+2.0** | 66% |
| 3_late(2-10m) | -3-6c | 57 | **+1.3** | 68% |
| 4_clutch(<2m) | +6-10c | 21 | **+1.2** | 57% |
| 2_mid(10-30m) | +18c+ | 19 | **+0.5** | 47% |
| 3_late(2-10m) | +6-10c | 35 | **-0.3** | 57% |
| 2_mid(10-30m) | +6-10c | 49 | **-3.2** | 49% |
| 2_mid(10-30m) | +10-18c | 35 | **-3.3** | 49% |
| 1_early(>30m) | +6-10c | 50 | **-4.2** | 42% |
| 3_late(2-10m) | +3-6c | 47 | **-6.3** | 53% |
| 2_mid(10-30m) | +3-6c | 63 | **-6.8** | 49% |
| 1_early(>30m) | +3-6c | 60 | **-9.8** | 38% |

### Survivors — positive net edge in BOTH halves (the only cells worth a strategy)

| time | gap | disc net ¢ | disc games | hold net ¢ | hold games |
|---|---|---|---|---|---|
| 4_clutch(<2m) | -18c+ | +16.5 | 23 | +20.4 | 18 |
| 4_clutch(<2m) | +18c+ | +11.5 | 29 | +13.0 | 15 |
| 4_clutch(<2m) | -10-18c | +5.3 | 33 | +10.6 | 20 |
| 4_clutch(<2m) | -6-10c | +5.1 | 38 | +4.6 | 27 |
| 4_clutch(<2m) | +10-18c | +4.7 | 32 | +4.9 | 16 |
| 4_clutch(<2m) | +3-6c | +1.5 | 45 | +3.8 | 30 |
| 4_clutch(<2m) | -3-6c | +0.8 | 47 | +3.2 | 29 |

