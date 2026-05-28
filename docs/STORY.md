# I built a robot to beat Kalshi sports markets. The market won. Here is everything.

So I had this idea. Kalshi lets you trade real money on whether a team wins a game. The
price moves live, like a stock. I figured: ESPN gives away a live win probability for free,
the price and the win probability should disagree sometimes, and when they disagree you bet
the gap and print money. Easy. Right?

I gave the whole thing to an AI and told it to act like a quant and go find the edge. Then I
watched what happened. This is the story.

## The lab

First we built the machine. Not a strategy, the whole machine.

A capture daemon that sits on a tiny free Google Cloud box and watches every NBA and WNBA
game live. It records the Kalshi price every time it ticks, plus every public trade, plus
the ESPN play by play and win probability. All day, every day, forever.

A backtest engine that replays a finished game second by second and lets a strategy trade
it, paying real Kalshi fees and a slippage assumption, so the numbers are not fantasy.

A data moat. Every settled game gets saved with its price candles, its play by play, its
order flow, and the official result. We ended up with 303 games on disk.

And a research loop. A headless AI that wakes up daily, reads how the lab is doing, tries an
idea, and is graded against one number. The goal was a system that improves itself.

Then we let it hunt.

## The gut punch

The first real test was simple. Is the Kalshi price actually good, or is ESPN better? You
measure this with a Brier score. Lower is sharper.

Kalshi price: 0.1181. ESPN win probability: 0.1181.

Identical. To four decimals. The market already knows everything ESPN knows. The gap I was
going to trade is not information, it is noise. There is nothing to bet.

Okay. Annoying. But maybe the edge is faster. Maybe order flow, the actual buying and
selling, predicts the next little move. We had every trade. We checked.

Nothing. The price reacts to a flood of buying in about zero seconds. By the time you see
the flow, the move already happened.

## The bug that almost fooled me

Here is the part that still makes me sweat.

While all the real strategies were coming back flat, our backtest had a control strategy in
it. A dumb one. It is supposed to lose money. It is literally labeled "do not trust this." It
exists to prove the test is honest.

It was showing plus 11 dollars a game.

That is not a good sign. That is a smoke alarm. If your known junk strategy is winning, your
test is lying to you.

We dug in. The bug was timing. When a team scored, the win probability updated instantly,
but our price data was a one minute bar that could be up to 60 seconds old. So the strategy
was buying at a price from before the play, a price nobody could actually trade at anymore.
It was peeking into the past and calling it skill.

We fixed it. You now fill at the price that comes after your signal, the one you could really
get. Every single strategy went negative. Including the ones that looked like winners.

That fix was the most valuable thing we did. A leak does not just give you a wrong number, it
gives you a flattering one, and a flattering number gets funded. If we had trusted it we
would have put real money behind a strategy with no edge and watched it bleed. The whole
point of the rigor was to catch the lie before the lie costs you.

## Every other door we tried

Once the engine was honest, we went down the list.

WNBA, a thinner and newer market. Still efficient.

Arbitrage against the sportsbooks. ESPN quietly hands you the DraftKings line. We stripped
out the bookmaker vig and compared. Across 294 games Kalshi tracks the sharp book within about 2 cents and never
disagrees by more than 4. No gap to arb. If anything Kalshi was a hair sharper than the book.

Scalping the swings. The price is basically a coin flip from second to second. After a big
move it keeps going more often than it reverses. You cannot fade it.

Market making, where you do not predict anything, you just quote both sides and earn the
spread. This one actually had a tiny real edge, about a third of a cent per contract. But
Kalshi takes a maker fee that eats most of it, and you net about a tenth of a cent. Real, but
too thin to be a business.

## What I actually learned

The market is smart. Not a little smart. Annoyingly, completely smart. Anything you can see
for free on ESPN, ten thousand other people can see too, and the price already ate it. A
liquid market on a popular sport is not where a solo person with public data finds free money.

Leaks flatter you. The scariest bugs are not the ones that crash, they are the ones that make
you look like a genius. Build the test to embarrass itself. Put a strategy in it that should
lose, and panic when it wins.

Knowing where the money is not is worth a lot. We have a clean map now of five dead ends. We
will not waste another hour on them, and neither should you.

And one more. The boring discipline paid for itself in a single bug. Calibration first. Trust
nothing. Guilty until proven.

## So did we make money

Not on sports. We proved you probably cannot, and that is a real result.

But the same logic that killed sports points at where an edge should live. Not a popular
market everyone watches. A market governed by something you can actually model, that the
sharps cannot be bothered with. We found a lead there. That part is staying quiet for now.

If you want to poke at the whole thing, the system and all 303 games of data are open here:
github.com/sayujjain04/Kalshi-Strat-Tester. Go check our work. Tell me where we were wrong.

We built a machine to find treasure and instead drew a very good map of where it is not.
Turns out that is most of the job.
