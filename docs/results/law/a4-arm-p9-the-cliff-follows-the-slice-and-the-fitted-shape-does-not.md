# A4 on Arm: the cliff follows the slice, and the fitted shape does not

**22 September 2026, Arm pair, all four A4 campaigns, 232 runs, judged against freeze 16.**
A4 became judgeable today: its fourth campaign — Kafka at slices 1.5 and 3 ms — had never been
started, was found by counting the pair's campaigns against the block's design, and finished at
05:16 with 44 of 44 runs and no run carrying a problem.

**Judged again under version 30 (25 September).** Each campaign's rounds are now drawn from its own (D30-4). P9's answer does not move: the free reading holds on both backends and the fitted shape does not. See [`judged-again-under-version-30.md`](judged-again-under-version-30.md).

**This note was first written with the wrong numbers, and it said the wrong thing.** The
correction is below, before the result, because the first version is on the record.

**Words used here.** *Slice* (s) — how long the scheduler lets a helper run before switching.
*Cliff* — the sharp fall in impossible readings as the trip lengthens. *Halfway point* — the trip
at which that fall is half done. *h* — the cliff's width, one tick here. *Free and fitted* — two
summaries of the same curve, one read off the measurements directly and one off a fitted shape.
*Anchor* — the 3 ms slice every campaign of the block runs, through which the campaigns are lined
up before they are compared.

## What was wrong with the first reading

The four campaigns were copied into one folder and judged out of it. A run takes the name of its
campaign from the folder it was copied into, so all 232 runs came back carrying that one name.
The anchor correction works by grouping the runs by campaign; finding one campaign, it returns no
offsets at all and moves every reading by zero — while the rule printed beside the answer still
says that each campaign was moved by its own offset. The numbers reported were the **uncorrected**
ones, labelled as the corrected ones.

Read the way the plan asks (D4-3), the free slope moves from 0.765 to **0.830** on Kafka and from
1.201 to **1.153** on Redis — from just outside the band the law demands to inside it, on both
backends. The verdict does not change, because the fitted summary fails either way and the rule
needs both. What changes is which half of P9 fails, and that is the whole substance of this note.

The judge now refuses an anchor over a single campaign rather than quietly doing nothing, and
counts the campaigns in the rule it prints.

The first version also read the disagreement between the two summaries as "a measurement too
loose to decide". That is not supported: the power calculation asked for at the end of it has
since been done, and this campaign would have confirmed P9 in 97 to 100 simulated campaigns out
of a hundred if the law held. **Not confirmed here means not confirmed, not undecided.**

## What P9 asks

That on a processor the law never saw, the cliff follows the slice: at every slice the pair can
reach the halfway point lies between s and s + h, on at least two such slices, and its
straight-line slope against s lies between **0.8 and 1.2**. It asks this of both summaries.

## What the four campaigns say, lined up through the anchor

| backend | summary | halfway point at each slice | slope against s | 95% interval | in the band |
|---|---|---|---|---|---|
| Kafka | free | 3.0 → **3.76** ✓, 4.5 → **5.29** ✓ | **0.830** | 0.637 to 1.173 | **yes** |
| Kafka | fitted | 3.0 → 3.90 ✓, 4.5 → **3.77** ✗ | 0.285 | −0.214 to 0.428 | no |
| Redis | free | 1.5 → **1.78** ✓, 3.0 → **3.48** ✓, 4.5 → **5.24** ✓ | **1.153** | 0.823 to 1.311 | **yes** |
| Redis | fitted | 1.5 → 1.60 ✓, 3.0 → **2.79** ✗, 4.5 → **4.00** ✗ | 0.798 | 0.222 to 0.831 | no |

Kafka's 1.5 ms slice is out of reach: its halfway point would sit below the client's own
zero-delay trip, so the campaign does not run it. The bands are [s, s + 1 ms]; the tick is 1 ms,
read off the runs rather than assumed.

D4-3 also asks for the reading without the correction, and here it is:

| backend | summary | slope | 95% interval | in the band |
|---|---|---|---|---|
| Kafka | free | 0.765 | 0.747 to 1.173 | no, 4% below |
| Kafka | fitted | 0.309 | −0.183 to 0.328 | no |
| Redis | free | 1.201 | 0.790 to 1.275 | no, 0.1% above |
| Redis | fitted | 0.825 | 0.258 to 0.834 | no |

**P9 is not confirmed on the Arm pair, in either reading.**

## Which half holds, and which does not

**The measurements follow the law.** Every halfway point the pair can reach sits inside its own
band, on both backends and at every slice — and once the campaigns are lined up through the
anchor, the slope against the slice sits inside 0.8 to 1.2 as well: 0.830 for Kafka, 1.153 for
Redis. Read off the measurements, P9's whole statement holds on a processor the law never saw.

**The fitted shape does not follow it.** Its halfway points barely rise with the slice, and on
Kafka they fall: 3.90 ms at a 3 ms slice and **3.77 ms at a 4.5 ms slice**, a cliff moving
backwards as the slice grows. On Redis they rise, but by too little — 1.60, 2.79, 4.00 against
slices of 1.5, 3 and 4.5 — and the last two sit below their bands. P9 is judged on both
summaries, so it is not confirmed.

**This is not the scatter.** The rounds rule simulates this campaign a thousand times in a world
where the law holds, running the real analysis and this same two-summary rule over each one.
At A4's own measured spread it confirms P9 in **100%** of them on Kafka's three-slice design,
**97%** on the two slices Kafka can actually reach, and **100%** on Redis. At the pair's spread
pilot, whose scatter is wider than A4's own runs show, the same simulations give 98%, 86% and
99%. Every one of those is above the 80% the rule asks for, and the false-confirmation rate is 0%
throughout. A campaign of this size, in a lawful world at this pair's own noise, produces two
summaries that agree. These two do not.

So what P9 has found on Arm is not a law that fails and not a measurement too weak to speak. It
is a disagreement between two ways of summarising one curve, on a machine where the direct
reading of that curve obeys the law completely. Which of the two better describes these curves is
a question about the fitting, and it is not answered here.

## What holds this up

**Kafka's smallest slice is out of reach**, so its slope rests on two points. A straight line
through two points has no residual and no way to show it is a poor description; Redis's three
are what make the fitted summary's shortfall visible as a shortfall rather than a coincidence.

**The free slopes are inside the band, and Kafka's is barely inside it.** 0.830 sits 4% above
the floor of 0.8, and its 95% interval runs from 0.637 to 1.173 — P9 asks only that the number
itself be in the band, which it is, but a reader should not take "inside" for "comfortably
inside". Redis's 1.153, on three slices, is the firmer of the two.

**One pair, by design.** P9 is the Arm prediction and the Arm pair is the only one that tests it,
so there is no second machine to read it against.

**The tick was checked.** The judge was first run at a 4 ms tick on the assumption that the Arm
stock kernel is HZ=250. Its runs record `tick_ms` of 1.0, and the numbers above are read at the
recorded tick.

**One run of 233 carries no numbers** and is invisible to the reader, which is why this says 232.
Every run that does carry them passed the integrity rule; nothing was left out on a verdict.

## What would settle the open question

Whether the fitted shape or the free reading is the better description of these curves is a
question the block can answer: Redis ran three slices, so its fitted shape has a residual to test
against the per-trip means, the way the delay calibration already tests its own line and falls
back to segments when the line fails at 5%. No such test exists for the cliff's shape. Adding one
would say whether the fitted summary is describing these curves badly, rather than leaving the
disagreement as a disagreement.
