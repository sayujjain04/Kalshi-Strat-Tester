# FLOW SCAN — EXP-006: does order-flow predict the next price move?

_`research/edge_discovery.py --flow`. 291 games with enriched flow. Decide at each 30s flow bucket's close, enter de-leaked, measure forward mid move in the flow's direction. Game-clustered; 60/40 OOS time-split._

> GROSS = does flow predict direction (signal, ignoring cost). NET = after the round-trip you'd actually pay (2× spread + 2 fees) — the real tradeable bar. A real edge needs GROSS>0 in BOTH halves AND NET>0.

| horizon | flow strength | games(d/h) | GROSS disc ¢ | GROSS hold ¢ | gross+% | NET disc ¢ | NET hold ¢ |
|---|---|---|---|---|---|---|---|
| 30s | flow50-200 | 172/111 | +0.14 | -0.09 | 43% | -2.34 | -3.39 |
| 30s | flow200-1k | 174/117 | +0.05 | -0.00 | 54% | -2.59 | -3.46 |
| 30s | flow1k+ | 174/117 | +0.00 | +0.02 | 50% | -2.86 | -3.51 |
| 60s | flow50-200 | 171/107 | +0.11 | -0.20 | 47% | -2.39 | -3.63 |
| 60s | flow200-1k | 174/116 | +0.05 | -0.03 | 52% | -2.60 | -3.53 |
| 60s | flow1k+ | 174/117 | -0.00 | +0.02 | 45% | -2.87 | -3.51 |
| 120s | flow50-200 | 169/107 | +0.08 | -0.27 | 50% | -2.47 | -3.73 |
| 120s | flow200-1k | 174/116 | -0.06 | +0.06 | 48% | -2.74 | -3.46 |
| 120s | flow1k+ | 174/117 | +0.03 | +0.00 | 52% | -2.84 | -3.53 |

**GROSS signal survives OOS in 2 cells; NET (tradeable after round-trip cost) in 0.**
_Gross-positive-but-net-negative = flow predicts direction but the move is too small to clear the round-trip cost (a real finding: signal exists, not harvestable this way — would need a maker/spread-capture execution, not a spread-crossing taker)._
