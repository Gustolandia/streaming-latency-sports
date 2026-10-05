# Judged with and without what the brake only recorded: every prediction on all the data

**27 and 28 September 2026, on every run the three pairs made.** Each pair's disk was rebuilt at
home from the copies of 25 and 27 September and checked file by file against the list its driver
wrote at the last collection. Every judge is the frozen one of plan version 32 (as at `b7bfa091`),
run through `scripts/judge_campaigns.py`; the views are laid out by `scripts/brake_views.py`. The
answers, all three ways, are in [`judged-27-sep/`](judged-27-sep/), with the quality of every
campaign in [`judged-27-sep/quality_by_campaign.csv`](judged-27-sep/quality_by_campaign.csv).

**Words used here.** A *verdict* is a prediction's answer by its frozen rule. From version 32 the
*got-it brake* records rather than stops (D32-1): what it would have said travels with each run. A
run is *flagged* when it was taken while the brake recorded and failed the check the brake would
have stopped on. D32-1 asks every prediction a recorded run bears on to be judged with and without
the runs the brake would have stopped, and this reads that two ways: without the flagged runs, which
is what D32-1 says, and without every run taken while the brake recorded, which is what a stopping
brake would have left and the reading D26-1 gave A5 at 2 CPUs.

## The answer D32-1 asked for

*Plain words:* no verdict changes. Every prediction gives the same answer on all the runs, on the
runs without the 14 flagged ones, and on the runs a stopping brake would have left.

| Prediction | Block, pair | 25 September | All runs | Without the 14 flagged | Without the 1,110 recorded |
|---|---|---|---|---|---|
| P1 | A1, first x86 | not confirmed | not confirmed | not confirmed | not confirmed |
| P2, P2b, P2d | A2, both backends | not confirmed | not confirmed | not confirmed | not confirmed |
| P2c | A2, Kafka / Redis | not confirmed / confirmed | not confirmed / confirmed | the same | the same |
| P3a | A3, five campaigns | not confirmed | not confirmed | not confirmed | not confirmed |
| P3b | A3, five campaigns | confirmed | confirmed | confirmed | confirmed |
| P4 | A7, first x86 | not confirmed | not confirmed | not confirmed | not confirmed |
| P6 | A6's recordings | not confirmed | not confirmed | not confirmed | not confirmed |
| P7 | A5, second x86 | not confirmed | not confirmed | not confirmed | not confirmed |
| P8 | A8, both x86 and Arm | not confirmed | not confirmed | not confirmed | not confirmed |
| P9 | A4, Arm | not confirmed | not confirmed | not confirmed | not confirmed |
| A9-1, A9-2, A9-2b | A9, all three pairs | not read | not confirmed | not confirmed | not confirmed |

Leaving out the flagged runs moves no measured value of P1 to P9 beyond its fourth decimal; the
widest move is an interval's upper end, P2's fitted ratio on Redis, from 2.37 to 2.45, and A9-1's
shares move by at most half a point. Leaving out every recorded run moves the most where it takes
away the most: the finished halves of the resumed days. P2b's
fitted ratio on Kafka goes from 5.36 to 6.13, P2's free ratio on Redis from 1.06 to 0.78, and P8's
Python-to-Java ratio on the Arm pair from 4.25 to 3.95, each on the same side of its rule.

## What the brake recorded

*Plain words:* 1,110 runs were taken while the brake recorded, in 22 campaigns, and it would have
stopped on 14 of them.

| Pair | Campaigns with recorded runs | Recorded runs | Flagged | Where the flags are |
|---|---|---|---|---|
| first x86 | 8 | 349 | 6 | A1's retry (1), A9 and its retry (2 and 3) |
| second x86 | 10 | 309 | 7 | A2's Kafka and Redis days on HZ=1000 (2 each), A5 at 2 CPUs (1), A9's retry (2) |
| Arm | 4 | 452 | 1 | A9 (1) |

The resumed days hold both kinds of run: their first halves were taken while the brake stopped and
their second halves while it recorded. A campaign reads the brake's word when it starts, so the
third x86 A3's retry, started at 18:57 UTC on 26 September, ran with the brake stopping, and so did
M0; neither is touched.

## What the new data changed

*Plain words:* the campaigns finished under version 32 put one prediction in reach that was not,
add a third x86 pair to A3's, and add three Arm campaigns to A8's. None changes a verdict's word.

- **P1 on Kafka is in reach, and is not confirmed.** A1's Kafka campaign at 3 and 3.75 ms (D27-3)
  and its retry give Kafka the four slices the rule needs; on 25 September it had three and was
  out of reach. The halfway point sits in its band at all four, but the free slope is 0.76 (95%
  interval 0.60 to 1.02) where the rule asks 0.8 to 1.2, and the fitted slope is 0.23. P1 on
  Redis is as it was: the free slope holds at 1.01, the fitted one does not.
- **A3 on the second x86 pair** (D27-4, and its retry): P3b confirmed on both, the plateau rising by
  0.048 and 0.041 from 75 to 88% load; P3a not confirmed on either. P3b is now confirmed on five
  campaigns on three machines, and P3a on none.
- **A8 on the Arm pair, four campaigns:** Python's plateau is 4.25 times Java's (4.01 to 4.56),
  where the rule allows 1.5; the campaign of 21 September alone reproduces its earlier 4.33.
- **A2** has three days on each of our builds for Redis and three on HZ=1000 for Kafka. The verdicts
  are those of 25 September; P2c on Redis stays confirmed, its fitted slope now 0.87 (0.81 to 1.03).
- **P6** reads a fourth part, Kafka on the second x86 pair, and over-predicts there as elsewhere:
  median ratios 2.49 (Arm, Kafka), 3.24 (first x86, Kafka), 2.63 (second x86, Kafka) and 13.08
  (first x86, Redis), no setup inside the band.

## A9, read for the first time

*Plain words:* the thread that stamps each acknowledgement was waiting for a processor in most
negative readings, everywhere; and counting, acknowledgement by acknowledgement, how often that
wait outlasted the trip's margin predicts the negative rate inside the plan's band, two thirds to
one and a half times, in most setups. The time-weighted form frozen in version 28 does not.

| Pair, backend | Negative readings mostly waiting, 75% / 88% load | A9-2: setups in band, median ratio | A9-2b: setups in band, median ratio |
|---|---|---|---|
| Arm, Kafka | 84.5% / 79.4% | 0 of 29, 0.105 | 16 of 29, 1.12 |
| Arm, Redis | 85.6% / 84.5% | 0 of 28, 0.104 | **26 of 28, 1.12** |
| first x86, Kafka | 80.5% / 79.9% | 0 of 28, 0.116 | **22 of 28, 1.18** |
| first x86, Redis | **91.7% / 91.1%** | 0 of 29, 0.162 | **24 of 29, 1.30** |
| second x86, Kafka | 83.1% / 80.6% | 0 of 14, 0.115 | 8 of 14, 1.13 |
| second x86, Redis | **92.0% / 91.6%** | 0 of 15, 0.165 | **12 of 15, 1.11** |

In bold, where the part meets its rule. **A9-1** asks at least 90% of negative readings to have
spent more than half of their time from arrival to stamp waiting for a processor; it holds for
Redis on both x86 pairs and nowhere else, and everywhere the share is between 79% and 92%. **A9-2**,
the waits' sum over the window, under-predicts by six to ten times. **A9-2b**, the share of
acknowledgements whose own wait outlasted T − g, meets the rule (two thirds of setups within 0.67
to 1.5, median at least 0.8) on four of the six parts and misses on Kafka on the Arm pair and on
the second x86 pair. A prediction holds only where every part does, so A9-2 and A9-2b are both not
confirmed; A9-2b is the one that comes close, and P6, which reads every thread's waits, over-predicts
by 2.5 to 13 times. The reading is the one fixed in version 30 (D30-6), before any A9 run existed.

## M0, read for the first time

*Plain words:* under bursts, Kafka's trip grows one for one with the delay added; Redis's grows
faster, and none of the four explanations the plan froze accounts for it.

| Backend | Slope of the trip against the delay added | Departure at 8 ms |
|---|---|---|
| Kafka | 0.995 (0.974 to 1.022) | −0.04 ms |
| Redis, one acknowledgement per message | 1.181 (1.121 to 1.285) | +1.44 ms |
| Redis, acknowledgements in batches of 200 | 1.307 (1.272 to 1.537) | +2.46 ms |

For Redis every hypothesis is dropped: arrivals shift by the delay (M-H1), the receive loop's own
costs replayed give a slope of 1.00 (M-H2), and M-H3 and M-H4 contribute less than 0.01 ms. One
caveat is the plan's own: the recording moved the trips it recorded by more than the 0.02 ms it
allows, 0.35 to 0.43 ms for Kafka and up to 0.65 ms for Redis at 8 ms, so the request-timing log
is to go off, and part of the Redis departure, read on the recorded runs (D31-1), may be the
recording's.

## The quality of every run

*Plain words:* the quality report read every campaign; it decides nothing, and it found pauses of
seconds on both x86 pairs that the Arm pair does not have.

| Pair | Campaigns | Runs | Counted | Repeats far from their fellows | Runs with pauses (messages) |
|---|---|---|---|---|---|
| first x86 | 59 | 3,197 | 3,157 | 136 | 112 (12,839) |
| second x86 | 62 | 2,746 | 2,714 | 191 | 109 (9,268) |
| Arm | 35 | 2,159 | 2,125 | 100 | 1 (4) |

A *pause* is a message that arrived more than 150 ms after it was sent, past the warm-up. On both
x86 pairs they come in both backends and in every block, the longest trip 20.6 s; they cost a run a
median of 0.7% of its messages, and more than 10% in seven runs (the worst, a calibration run at 8
ms added, 31%). The integrity rule counted these runs, and nothing here is judged again without
them. The 25 September review saw pauses of 0.35 to 2.3 s on the x86 pairs with the broker
acknowledging on time and the consumer late; their cause is still not recorded anywhere. The
repeats far from their fellows are registered in each campaign's report and kept, as the plan
says: a run whose conditions held is a result.

The six runs the registries list and no campaign holds are the run folders set aside as void (the
[issues register](issues-register.md) names both occasions); the 8,102 here are the registries'
8,108 without them.

## How the data was read

Each pair's disk was rebuilt from the whole-runs archive of 25 September with the copy of 27
September over it, and checked against the driver's own list of every file: 135,050 files for the
first x86 pair, 111,472 for the second and 88,475 for Arm, nothing missing and nothing extra. The
one link on the Arm pair, `stage0.log`, was made as a copy of the file it points to, as the driver's
fingerprint of it reads. Each campaign was laid out in a folder of its own as `collect_runs.py` lays
one out, every file a link into the checked tree, and each view is the same folders with runs left
out. The judges read each view unchanged, with the options the verdicts of 25 September used.

## Pocket dictionary

- **Brake (got-it brake)**: the check that stops a campaign when a run's "got it" time moves further
  from its setup's earlier runs than the added delay allows.
- **Flagged run**: a run taken while the brake recorded, on which it would have stopped.
- **Free reading / fitted shape**: a curve required only never to rise, and a plateau, straight
  fall and floor; a prediction passes only where both agree.
- **In reach**: a slice or load whose runs reach the plateau, the floor and most of the cliff.
- **Pause**: a message more than 150 ms late after the warm-up.
- **T − g**: the median trip less the median got-it delay, the margin by which a reading turns
  negative.
- **View**: the campaigns laid out again with some runs left out, for a judge to read unchanged.
