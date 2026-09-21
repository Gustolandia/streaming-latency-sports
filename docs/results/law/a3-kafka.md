# A3, Kafka: does load leave the cliff where it is, and raise the plateau?

This reports one campaign of the law experiment: block A3 on Kafka, run on the first x86 machine
pair on 19–20 September 2026. It is judged against **freeze 05** (plan version 9), which was in
force when the campaign ran and which created the two predictions it tests. Nothing here is
judged by a rule written after the runs were seen.

*Glosses. **Campaign**: the runs that answer one question in one sitting. **Round**: one pass
through every setup of a campaign once. **Setup**: one combination of settings. **Plateau, cliff,
floor**: the three parts of the predicted curve — a flat high rate at short trips, a fall, and a
low rate past it. **Halfway point**: the trip at which the rate has fallen halfway from the
plateau to the floor; this is "where the cliff is". **Negative rate**: the share of messages that
appear to arrive before they were sent.*

## What ran

| | |
|---|---|
| Block and backend | A3, Kafka |
| Pair | first x86 (`matched`) |
| Session | `matched_20260919T171733Z` |
| Conditions | 3 ms slice, 50/75/88% load, six trips, 18 setups |
| Rounds asked for | 16 |
| Runs planned | 288 |
| Runs finished | **286** |
| Rounds complete | **15** (18 runs each); round 16 has 16 of 18 |
| Collected | 11,189 files, each fingerprinted and checked |

*Glosses. **Slice**: how long the scheduler lets a helper run before switching. **Load**: how busy
the machine was kept. **Fingerprint**: a code computed from a file's bytes, so a copy can be
checked against the original.*

## How it ended

The campaign stopped itself in round 16, on a run at the plateau trip at 75% load:

> the got-it median moved −0.193 ms, more than 25% of the 0.575 ms added and more than the
> 0.117 ms this session's got-it moves by itself

This is the brake the plan puts on the "got it" reading (P5(c), and D8-2 of version 8), and it
did what it was built to do: it stopped and waited for a person.

**The cause, and whether it touched the earlier runs.** The got-it median drifts gently downward
across the session — 1.573 ms over rounds 1–4, then 1.565, 1.530 and 1.514 — a total of about
0.06 ms over 13.3 hours. Against every other campaign this pair has run, that rate is
unremarkable:

| campaign | hours | drift | per hour |
|---|---|---|---|
| A1 (four campaigns) | 2.8–4.2 | −0.029 to +0.015 | −0.0106 to +0.0053 |
| A7 | 2.1 | +0.018 | +0.0084 |
| P0 | 3.1 | −0.018 | −0.0059 |
| **A3** | **13.3** | **−0.058** | **−0.0043** |

A3's rate sits in the middle of that set, and the rates fall either side of zero, so this is
session wander rather than an instrument going bad. A3 tripped the brake because it **ran 13.3
hours instead of three**, so ordinary wander accumulated against a threshold that does not scale
with how long a campaign runs — and that threshold is a quarter of the *added delay*, which is
smallest at the plateau trip, where least delay is added. That is exactly where it stopped.

The brake was right about that one run: at 1.418 ms its got-it median is the lowest of all
sixteen rounds. The session-level reading, that the instrument had moved, is not supported by the
pair's own history. Under the plan's rule for a campaign that stops itself, runs finished before
the stop stand where the cause did not touch them; each of the 286 was checked by this same brake
as it ran, and each passed.

**Why the campaign closes at 15 rounds.** Results are resampled by whole rounds, so an incomplete
round cannot contribute one. The machines were deallocated when the campaign ended, which is a
reboot, so the session's calibration is gone; two further runs would be placed from a different
calibration and would leave round 16 with sixteen runs measured one way and two another. The
fifteen complete rounds are the balanced set. **Both predictions were judged twice — on the 15
complete rounds and on all 286 runs — and the two agree to three decimal places**, so this choice
decides nothing.

## What the campaign says

### P3b — load raises the plateau: **confirmed**

The plateau's increase between the lowest and the highest load, with its 95% interval:

| | estimate | 95% interval |
|---|---|---|
| free shape | +0.0874 | 0.0846 to 0.0904 |
| fitted shape | +0.0872 | 0.0840 to 0.0896 |

The rule asks for the interval to lie above zero. It does, with room to spare. The measured
plateau at each load:

| load | plateau | floor | halfway point |
|---|---|---|---|
| 50% | 0.15% | 0.05% | 3.438 ms |
| 75% | 4.10% | 0.93% | 3.406 ms |
| 88% | 8.89% | 2.91% | 3.397 ms |

### P3a — load leaves the cliff where it is: **not confirmed, and inconclusive**

| | estimate | 95% interval |
|---|---|---|
| free shape | −0.0405 ms | −0.381 to +0.264 |
| fitted shape | −0.0385 ms | −0.394 to +0.289 |

P3a is an equivalence test: it asks for the **whole** interval to fall inside ±0.25 ms, because a
point estimate inside the band can land there by luck. The interval is about ±0.32 ms wide, so it
does not, and the rule's verdict is **not confirmed**.

**This is not evidence that the cliff moved.** The estimate is −0.04 ms, and the three halfway
points above sit within 0.041 ms of one another across the full load range. A test of this shape
that lacks the precision to demonstrate equivalence yields an inconclusive result, not a negative
one; absence of evidence for equivalence is not evidence of a difference. The campaign did not
settle P3a either way.

**Why the precision fell short.** At 50% load the plateau is **0.15%** — the whole curve there
spans 0.0015 down to 0.0005. Locating a cliff in a curve that barely falls is badly conditioned,
and that load's halfway point is correspondingly imprecise; nearly all of the interval's width
comes from it. P4 already carries a guard for this, counting only where the ordinary plateau is
at least 2%; P3a carries no equivalent, and the plan did not anticipate the difference. **That
guard is not being added retrospectively**: the verdict above stands as the frozen rule gives it.

## A departure to report

P5(c) asks that the receiver-only delay leave the "got it" reading unchanged, and says that
where it does not, the session is analysed with each run's own got-it distribution and the
departure reported. This session departed: the drift above, and the excursion that stopped it.
Both are reported here, and both judgements above were computed per run.

## What follows

A3's Kafka campaign is closed. P3b's answer stands on this data. P3a is unresolved and will be
settled by a new campaign, designed to have the precision this one lacked and pre-registered
before it runs; this campaign is reported beside it, not replaced by it. The Holm correction
across a family of predictions is applied once a family's campaigns have all run, so the verdicts
above are the uncorrected ones.

## Pocket dictionary

| Word | Plain meaning |
|---|---|
| Equivalence test | a test that two things are the same within a stated margin |
| Inconclusive | the data cannot tell the two possibilities apart; not a finding either way |
| 95% interval | a range built so that 95 of 100 such ranges would hold the true value |
| Resampling | rebuilding the campaign many times from its own rounds, to see how much its answer moves |
| Free / fitted shape | two ways of reading the curve: from the measured levels, or from a shape fitted to them |
| Got it | the moment the broker's acknowledgement is seen by the sender |
| Calibration | measuring how much a known added delay moves our reading |
| Session | one machine pair, booted one way, on one day |
| Deallocate | switch a cloud machine off, which is a reboot and ends its session |

---

# The second campaign, 21 September 2026: twelve rounds under freeze 12

The first campaign stopped itself at 286 of 288 on the got-it brake. This one ran to the end:
**216 runs counted, 1 repeated, all 12 rounds, no stop.** Judged against **freeze 12** (plan
version 16), which was in force when it ran, and at 12 rounds because the rounds rule simulated
that count to confirm P3a in 84% of campaigns at the plateau, floor and spread this pair's own
spread pilot measured (D14-1).

*Provisional in one respect only: judged from each run's `queue_row.json` and `integrity.json`
read on the driver, because the pair went straight on to A3's Redis campaign and copying the
campaign home while it measures is not free. The formal collection, with a fingerprint for every
file, has not been done. The judge sees the same bytes either way.*

## What it says

**P3b — load raises the plateau — confirmed, and not narrowly.**

| summary | increase between the lowest and highest load | 95% interval |
|---|---|---|
| free shape | 0.0808 | 0.0779 to 0.0834 |
| fitted shape | 0.0834 | 0.0775 to 0.0845 |

The rule asks for an interval above zero. Both are, by a wide margin, and both shapes agree. This
is the same answer the 15-round campaign gave, from an independent campaign on the same pair.

**P3a — load leaves the cliff where it is — not confirmed, and not contradicted either.**

| summary | move between the lowest and highest load | 95% interval |
|---|---|---|
| free shape | +0.1298 ms | −0.7897 to +0.5377 |
| fitted shape | −0.3337 ms | −1.0685 to +0.7033 |

The rule is an equivalence test: the whole interval has to sit inside 0.25 ms either way. These
intervals are about five times that wide, so the campaign cannot place the cliff precisely enough
to say whether it moved. The two summaries do not even agree on the sign. **"Not confirmed" here
means the measurement is too imprecise to decide, not that the cliff moved.**

## The stated power does not survive recomputation

The campaign's own rounds note says **12 rounds, confirmed in 84% of 1000 simulated campaigns
under the law**. Recomputed on 21 September with the rounds rule as it now stands, at A3's own
design taken from `law_design.BLOCKS`, at the three levels that note itself quotes, and at the
note's own seed:

| rounds | confirms under the law | confirms where it is false |
|---|---|---|
| 12 — what the second campaign ran | **38.3%** | 0.0% |
| 15 — the first campaign's complete rounds | 51.1% | 0.0% |
| 16 — what the first campaign asked for | 54.6% | 0.0% |

1,000 simulated campaigns each, the same number the note quotes, so this is not a sampling
difference: 38.3% against 84% is not a number that moves with the seed.

**What follows from it.** P3a not confirming is what an underpowered campaign does. At 38%, a
campaign that runs under the law fails to confirm three times in five, and both A3 Kafka
campaigns landed there — the first at about 51%, the second at 38%. Two null results from two
campaigns is not two pieces of evidence about load and the cliff; it is one design, run twice,
that was unlikely to confirm either time.

**What does not follow.** Nothing here touches P3b, which confirmed in both campaigns with
intervals far from zero, and nothing here says the cliff does or does not move with load. The
measurement is of the instrument, not of the world.

**What is not yet known** is why the two numbers differ. The rule judging P3a has changed since
the 84% was computed — freeze 10 put a 2% floor on the plateau P3a may be judged at (D14-2), and
A3's plateau at 50% load is 0.15% — so the comparison the rule now makes may not be the one that
was simulated then. That is a reading of the code and its history, not a measurement, and it is
left open here rather than asserted.

## The part worth keeping

A3's Kafka plateau at the 3 ms anchor is 3.46%, above the 2% guard that freeze 10 put on P3a, so
this is not the shallow-curve problem that puts P3a out of reach on Redis. The campaign ran the
number of rounds a simulation said would confirm P3a in 84% of campaigns under the law, and it
did not confirm.

That is a statement about this campaign and its interval, and deliberately not a statement about
power: reading a failed confirmation backwards into "the power was low" is the observed-power
fallacy this plan refuses elsewhere. What it does mean practically is that the rounds rule's
answer for P3a rests on assumptions about the cliff's fitted position that a real campaign has now
twice failed to meet — at 15 rounds and at 12 — and that deciding what to do about it is a freeze
decision with two campaigns of evidence rather than one.
