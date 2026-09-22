# A4 on Arm: the cliff is where the law says, and does not move with the slice as the law says

**22 September 2026, Arm pair, all four A4 campaigns, 233 runs, judged against freeze 16.**
A4 became judgeable today: its fourth campaign — Kafka at slices 1.5 and 3 ms — had never been
started, was found by counting the pair's campaigns against the block's design, and finished at
05:16 with 44 of 44 runs and no run carrying a problem.

**Words used here.** *Slice* (s) — how long the scheduler lets a helper run before switching.
*Cliff* — the sharp fall in impossible readings as the trip lengthens. *Halfway point* — the trip
at which that fall is half done. *h* — the cliff's width. *Free and fitted* — two summaries of
the same curve, one read off the measurements directly and one off a fitted shape.

## What P9 asks

That on a processor the law never saw, the cliff follows the slice: at every slice the pair can
reach the halfway point lies between s and s + h, on at least two such slices, and its
straight-line slope against s lies between **0.8 and 1.2**.

## What the four campaigns say

| backend | summary | halfway inside its band | slope against s | 95% interval |
|---|---|---|---|---|
| Kafka | free | 3.0 ✓, 4.5 ✓ (1.5 out of reach) | **0.765** | 0.747 to 1.092 |
| Kafka | fitted | 3.0 ✓, 4.5 ✗ | 0.309 | −0.183 to 0.328 |
| Redis | free | 1.5 ✓, 3.0 ✓, 4.5 ✓ | **1.201** | 0.790 to 1.275 |
| Redis | fitted | 1.5 ✓, 3.0 ✗, 4.5 ✗ | 0.825 | 0.274 to 0.834 |

**P9 is not confirmed on the Arm pair.**

## Which half holds, and which does not

**The cliff is where the law puts it.** Read off the measurements, every halfway point the pair
can reach sits inside its own band — all three slices for Redis, both reachable ones for Kafka.
That is the part of P9 that says the law's shape survives a change of processor, and it survives.

**It does not scale with the slice as the law requires.** The slope misses the 0.8–1.2 band on
both backends, narrowly and in *opposite directions*: Kafka at 0.765 falls just below the floor,
Redis at 1.201 sits just above the ceiling. Both are within about 4% of the bound they miss, and
both 95% intervals straddle the band rather than sitting outside it.

**The two summaries disagree, and that is the most informative thing here.** The free and fitted
readings of the same curves give 0.765 against 0.309 for Kafka, and 1.201 against 0.825 for
Redis. Two summaries of one measurement do not differ by a factor of two when the measurement is
precise. Together with intervals that straddle the band in both directions, this reads as a
campaign that cannot place the slope tightly enough to decide, rather than as a law that fails —
the same shape as A3's P3a, where the point estimate sat near zero and the interval was five
times the band.

Saying so is not the same as showing it. **The honest position is that P9 is not confirmed and
the reason is not yet established.** What would settle it is a power calculation for P9's slope
clause at this pair's measured spread, done the way A3's was after its note was found to claim
84% where the rule gives 38.3%. A4 ran at 4 rounds against a stated 92–100%, and that figure has
not been recomputed since the rounds rule was corrected on 21 September (D14-1).

## What holds this up

**Kafka's smallest slice is out of reach**, so its slope rests on two points. A straight line
through two points has no residual and no way to show it is a poor description; Redis's three are
what make the disagreement between summaries visible at all.

**One pair, by design.** P9 is the Arm prediction and the Arm pair is the only one that tests it,
so there is no second machine to read it against.

**The tick was checked.** The judge was first run at a 4 ms tick on the assumption that the Arm
stock kernel is HZ=250. Its runs record `tick_ms` of 1.0, and re-judged at the recorded tick the
numbers above are identical to the digit — but the first reading was against the wrong band and
would have been reported without anyone noticing had the tick not been checked against what the
runs carry.
