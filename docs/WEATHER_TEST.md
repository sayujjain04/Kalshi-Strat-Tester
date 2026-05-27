# WEATHER TEST — EXP-011: does Kalshi overprice temperature uncertainty?

_`research/weather_test.py`. 67 city-date events across 1 cities, morning reference price (event-day 14:00Z, before the afternoon high — no look-ahead). Same rigor as sports: calibration + tradeable expectancy net of fees, event-clustered, 60/40 OOS split._

## 1. Calibration — do tail buckets win less than priced? (overpricing signature)
| morning implied band | n buckets | mean implied | realized win% | over/under |
|---|---|---|---|---|
| 0.00–0.05 | 177 | 0.015 | 0.000 | OVERPRICED |
| 0.05–0.10 | 44 | 0.064 | 0.091 | underpriced |
| 0.10–0.20 | 51 | 0.136 | 0.059 | OVERPRICED |
| 0.20–0.40 | 53 | 0.292 | 0.189 | OVERPRICED |
| 0.40–0.70 | 65 | 0.495 | 0.585 | underpriced |
| 0.70–1.01 | 12 | 0.860 | 1.000 | underpriced |

## 2. Tradeable expectancy (hold to settlement, net of fee)
| strategy | disc exp/bet | disc n | hold exp/bet | hold n | disc win% |
|---|---|---|---|---|---|
| BUY modal bucket | +1.36¢ | 40 | +13.94¢ | 27 | 52% |
| SELL cheap tails (NO) | -0.92¢ | 127 | +0.20¢ | 94 | 46% |
