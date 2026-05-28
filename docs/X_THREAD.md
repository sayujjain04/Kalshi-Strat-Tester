# X thread: the Kalshi lab story

Tip: each post has a [chart] note for what to attach. The numbers are the hook, the chart
makes people stop scrolling. Most charts are one screenshot of a table or one line plot from
the open data.

---

**1/**
i built an autonomous AI lab to beat Kalshi sports betting markets with real money.

it ran for weeks. tested 5 different ways to win. the market beat every single one.

here is the whole story, every dead end, and all 303 games of data, open. 🧵

[chart: a clean title card, or a screenshot of the live dashboard board]

---

**2/**
the setup was simple and i was sure it would work.

ESPN gives away a live win probability for every game, for free. Kalshi has a live price for
the same game. when they disagree, bet the gap. print money.

so i built the machine to do it automatically.

[chart: one game's timeline with two lines, ESPN win prob and the Kalshi price, moving together]

---

**3/**
the machine:

a daemon on a free google cloud box watching every NBA + WNBA game live, saving every tick.
a fee aware backtester. a 303 game dataset (price, play by play, win prob, order flow,
results). and an AI that wakes up daily and tries new strategies on its own.

[chart: screenshot of the data inventory / 303 games on disk]

---

**4/**
then the gut punch.

i measured who is sharper, ESPN or the market, with a Brier score (lower = better).

ESPN: 0.1181
Kalshi: 0.1181

identical. the market already knows everything ESPN knows. the gap i wanted to trade is not
information. it is noise.

[chart: the calibration table, ESPN vs Kalshi Brier side by side]

---

**5/**
here is the part that still makes me sweat.

my backtest had a junk strategy in it. on purpose. it is supposed to LOSE. it exists to prove
the test is honest.

it was showing +$11 per game.

that is not a win. that is a smoke alarm. if your known bad strategy prints money, your test
is lying to you.

[chart: bar showing the control strategy at +11.82, flagged red]

---

**6/**
the bug was time travel.

when a team scored, the win prob updated instantly, but my price data was a 1 minute bar that
could be 60 seconds stale. so the bot was buying at a price from BEFORE the play. a price
nobody could actually get.

it was peeking at the past and calling it skill.

[chart: a diagram, signal at T, but filling at the price from T minus 60s]

---

**7/**
i fixed it. you now fill at the price that comes AFTER your signal, the one you could really
trade.

every strategy went negative. including the ones that looked like winners.

control strategy: +11.82 became negative 10.45.

best lesson of the whole project: leaks do not just give you a wrong number, they give you a
flattering one. and flattering numbers get funded.

[chart: before vs after table, every strategy flipping from green to red]

---

**8/**
once the engine was honest i went down the list.

WNBA (thinner market): still efficient.
arb vs the DraftKings line (ESPN hands it to you free): Kalshi tracks it within 2 cents over
294 games, never off by more than 4.
scalping the swings: price is a coin flip, you cannot fade it.

every door, locked.

[chart: histogram of Kalshi vs DraftKings price gaps, almost all under 2 cents]

---

**9/**
the only thing with a real edge was market making. dont predict anything, just quote both
sides and earn the spread.

gross edge: about +0.35 cents per contract. real!
then Kalshi takes a maker fee.
net: about +0.07 cents. technically positive. too thin to be a business.

[chart: the fee sensitivity table, edge shrinking as the fee grows]

---

**10/**
what i actually learned:

the market is smart. anything free on ESPN, 10,000 people see too, and the price ate it.

leaks flatter you. build your test to embarrass itself.

and knowing where the money is NOT is worth a lot. i have a clean map of 5 dead ends now.

system + all 303 games, open: github.com/sayujjain04/Kalshi-Strat-Tester

we built a machine to find treasure and drew a very good map of where it is not. that is most
of the job. (the part that is not a dead end, i am keeping quiet for now.) 🌦️
