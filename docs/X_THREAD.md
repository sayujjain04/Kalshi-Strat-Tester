# X thread: the Kalshi lab story (daily log version)

Charts live in `docs/charts/`. The [attach: file.png] note tells you which image goes on
which post. Voice is raw, no dashes.

---

**1/ the hook**

i built an autonomous AI lab to find a real money making edge in prediction markets.

i gave it a quant's brain, every tick of real market data, and a single instruction: go find
the edge, and do not lie to yourself.

then i let it run for weeks. this is the daily log. every experiment, every dead end, the one
bug that almost fooled me, all of it. 🧵

[attach: 07_overview.png]

---

**2/ what it actually is**

not a strategy. a whole machine.

a capture daemon living on a free google cloud box, awake 24/7, recording every NBA and WNBA
game tick by tick. a fee aware backtester that replays a finished game second by second. and
an AI research loop that wakes up daily, tries an idea, and is graded against one number.

it is keyed to do exactly one thing: get less wrong over time.

---

**3/ the rules i fed it**

before it could touch anything i gave it an operating charter. the core of it:

calibration first. disconfirmation first. every edge is guilty until proven innocent. a clean
win rate on a small sample is a red flag, not a green light.

basically: act like the smartest skeptic in the room, especially about your own ideas.

---

**4/ the data moat**

you cannot find an edge you cannot measure, so step one was just collecting everything.

303 settled games. each one saved with its price candles, the full ESPN play by play, the
live win probability, the condensed order flow, and the official result.

this is the foundation. it is open. link at the end.

[attach: 07_overview.png]

---

**5/ Experiment 1: the obvious idea**

ESPN gives a live win probability for every game, free. Kalshi has a live price for the same
game. my whole thesis: when they disagree, bet the gap.

here is one game. the blue line is ESPN's win prob, the orange is the Kalshi price.

watch how tightly they move together. that was the first bad sign.

[attach: 01_winprob_vs_price.png]

---

**6/ Experiment 1 result: the gut punch**

i measured who is actually sharper with a Brier score (lower is better). plotted the
reliability curve: predicted chance on the x axis, what actually happened on the y.

ESPN: 0.1181. Kalshi: 0.1181. identical to four decimals. both lines sit right on top of
perfect calibration.

the market already knows everything ESPN knows. the gap is not a signal. it is noise.

[attach: 02_calibration.png]

---

**7/ the bug that almost fooled me**

while the real strategies came back flat, my backtest had a junk control strategy in it. on
purpose. it is supposed to LOSE. it proves the test is honest.

it was showing plus 11 dollars a game.

a known junk strategy printing money is not a discovery. it is a smoke alarm. it means your
test is lying to you.

[attach: 03_the_leak.png]

---

**8/ the leak, in detail**

the bug was time. when a team scored, the win prob updated instantly, but my price data was a
one minute bar that could be 60 seconds stale.

so the bot was buying at a price from BEFORE the play. a price nobody could trade anymore. it
was peeking into the past and calling it skill.

i fixed it: fill at the price that comes AFTER your signal. every strategy went negative.

biggest lesson of the whole project: leaks do not give you a wrong number, they give you a
flattering one. and a flattering number gets funded.

---

**9/ Experiment 2: order flow**

okay the gap is dead. but maybe speed wins. maybe the actual buying and selling predicts the
next little move. i had every trade, so i checked.

forward return after a flow burst, at 30, 60, 120 seconds: basically zero. noise.

the price reacts to a flood of buying in about zero seconds. by the time you see the flow, the
move already happened.

[attach: 04_flow.png]

---

**10/ Experiment 3: arbitrage**

new angle. ESPN quietly hands you the DraftKings line for free. so i de vigged it and compared
it to Kalshi. if they disagree, that is free money.

across 294 games they agree within about 1 cent on average, and never more than 4. the fee to
trade is bigger than the gap. no arb. Kalshi was even a hair sharper than the book.

[attach: 05_cross_venue.png]

---

**11/ Experiment 4: market making**

last idea. stop predicting. just quote both sides and earn the spread, like a tiny casino.

this one actually had a real edge. about plus 0.35 cents per contract gross. but Kalshi takes
a maker fee, and at their real rate it nets to about plus 0.07 cents.

technically positive. way too thin to be a business. the fee gate kills it.

[attach: 06_market_making.png]

---

**12/ what i actually learned**

the market is smart. annoyingly, completely smart. anything free on ESPN, ten thousand people
see, and the price ate it. a popular liquid market is not where a solo person finds free money.

leaks flatter you. build your test to embarrass itself.

and knowing where the money is NOT is worth a lot. i have a clean map of five dead ends now.

---

**13/ so did it work**

not on sports. and proving that, rigorously, IS the result.

but the same logic that killed sports points somewhere better. not a market everyone watches.
a market governed by something you can actually model, that the sharps ignore. i found a lead
there. heads down on it now, quietly. 🌦️

the full system and all 303 games are open. go check my work, tell me where i am wrong:
github.com/sayujjain04/Kalshi-Strat-Tester
