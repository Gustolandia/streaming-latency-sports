# Judged again under version 30: what the corrected programs say, beside what they said before

**25 September 2026, judged by `ce153e74` (plan versions 30 and 31) on exactly the runs each
earlier answer read.** No new run went into anything here. Version 27 found five places where the
programs that judge the predictions departed from the plan's own text (D27-5). Version 30 corrected
them (D30-1 to D30-5) and asked for every verdict they touch to be judged again, with the reading as
it was beside it. This is that, and the first reading of P6, which had no program until version 30.

**Words used here.** A *verdict* is a prediction's answer by its frozen rule. Every cliff is summed
up two ways, the *free reading* (a curve only required never to rise) and the *fitted shape* (a
plateau, a straight fall and a floor), and a prediction passes only where both agree. A slice is
*in reach* when the runs reach the plateau, the floor and most of the cliff; a campaign that reaches
too few slices *did not test* the prediction, which is now reported as *out of reach* rather than
as a result against it.

## What moved

*Plain words:* the table gives each verdict before and after. Most words are unchanged; three
changed, and each change is the correction doing what the plan's text always said.

| Prediction | Block, pair | Before | Now | What moved it |
|---|---|---|---|---|
| P1 | A1, Kafka, first x86 | not confirmed | **out of reach**: 3 slices where the rule needs 4 | D30-3 |
| P1 | A1, Redis, first x86 | not confirmed | not confirmed | nothing: the fitted shape still misses |
| P7 | A5, Kafka, second x86 | not confirmed | **confirmed at 8 CPUs**; 2 and 4 CPUs out of reach | D30-2, D30-3 |
| P7 | A5, Redis, second x86 | not confirmed | not confirmed | the free reading now holds; the fitted shape misses |
| P3a | A3, Kafka, first x86 (19 Sep) | not confirmed, 50 against 88% | not confirmed, 75 against 88% | D30-1 |
| P3a | A3, Kafka, first x86 (21 Sep) | not confirmed, 50 against 88% | not confirmed, 75 against 88% | D30-1 |
| P3a | A3, Kafka, Arm | not confirmed, 50 against 88% | not confirmed, 75 against 88% | D30-1 |
| P3b | A3, all three | confirmed | confirmed | D30-1 changes the numbers, not the answer |
| P2, P2b, P2c, P2d | A2, both backends | as before | as before | D30-4 changes the intervals |
| P9 | A4, Arm | not confirmed | not confirmed | D30-4 changes the intervals |

The old answers are in the documents each block has (for A3, [`a3-kafka.md`](a3-kafka.md); for A4,
[`a4-arm-p9-the-cliff-follows-the-slice-and-the-fitted-shape-does-not.md`](a4-arm-p9-the-cliff-follows-the-slice-and-the-fitted-shape-does-not.md)).

## P1 on Kafka was never a result against the law

*Plain words:* at the A1 sessions' own zero-delay trip, 2.21 ms, Kafka reaches three slices and the
rule needs four, so this campaign could not test P1 on Kafka at all.

Read through the 3 ms anchor, the free reading's slope is 0.756 (95% interval 0.641 to 0.995) and all
three reachable halfway points sit in their bands; the fitted shape's slope is 0.320. The answer
used to be "not confirmed", which reads as the law failing. It is "out of reach", which is what it
was. The Kafka campaign at 3 and 3.75 ms that version 27 added runs on the first x86 pair from
tonight; with it Kafka reaches four slices.

On Redis nothing moved. Five slices are in reach; the free reading holds, slope 1.007 with an
interval of 0.844 to 1.169 (at 200 draws before, drawn by round number, it was 0.722 to 1.219), and
the fitted shape does not: slope 0.662, three of five halfway points outside their bands.

## P7: confirmed on Kafka at the one core count this pair can test

*Plain words:* the machine reports the slice the core-count rule computes at every core count, and
on Kafka the cliff sits where that slice says, at the one core count whose slice Kafka can reach.

The read-back matches at 2, 4 and 8 CPUs on both backends. On Kafka, the slices the kernel picks at
2 and 4 CPUs lie under Kafka's own zero-delay trip, so the runs cannot reach them; at 8 CPUs the
halfway point is inside its band on both summaries. That is a weaker test than three core counts,
and it is reported as what it is. The old program also asked P9's slope across core counts, which
P7 never asks, and with one core count in reach no slope exists, so it could not confirm.

On Redis every core count is in reach. The free reading's halfway point is inside its band at all
three; the fitted shape's is outside at all three, the same split as P1 and P9 show on Redis. The
answer is the same with and without the thirteen runs taken with the got-it brake recording (D26-1).

## P3a and P3b now compare the loads that have a plateau

*Plain words:* at 50% load the plateau is so low (0.12 to 0.16% of messages) that no cliff can be
located in it, so the comparison is between 75% and 88%, as D14-2 has said since version 14.

The corrected judge puts 50% load out of reach on all three campaigns (plateaus 0.0015, 0.00124 and
0.00159) and compares 75 with 88%. Its answers reproduce, to four decimals, the answers taken by hand
with the same two loads, which checks D30-1 against D14-2.

**P3b is confirmed on all three**: the plateau rises by 0.048, 0.047 and 0.050 of messages from 75 to
88% load, every interval well above zero.

**P3a is confirmed on none.** It asks the whole interval of the halfway point's move to sit inside
0.25 ms either way:

| Campaign | Free reading, ms | Fitted shape, ms |
|---|---|---|
| Kafka, first x86, 19 Sep | −0.009 (−0.126 to 0.178), inside | −0.040 (−0.253 to 0.234), just outside |
| Kafka, first x86, 21 Sep | −0.188 (−0.384 to 0.056), outside | −0.165 (−0.265 to 0.099), outside |
| Kafka, Arm | −0.309 (−0.383 to 0.088), outside | −0.247 (−0.330 to 0.038), outside |

The first campaign misses by 0.003 ms on one summary. The second and the Arm campaign put the cliff
0.17 to 0.31 ms earlier at 88% load, an equivalence test's interval reaching past the band rather
than a clear move. Against 50%, the Arm interval ran from −0.158 to 0.618; against 75%, it runs from
−0.383 to 0.088: 0.61 times as wide, the narrowing D14-2 predicted a load with a plateau would buy. The
third x86 A3 campaign, 16 rounds at 75 and 88% only, runs on the second x86 pair tonight.

## P6: the first reading, and it over-predicts

*Plain words:* half of A1's and A3's runs recorded how long every `python3` thread waited for a CPU.
P6 asks whether that recording, with nothing fitted, predicts how often readings come out negative.
It does not: it predicts two and a half to thirteen times too many.

Each recorded run's rate is predicted as the share of its recorded waits longer than T − g, its median
trip less its median "got it" delay, as version 30 froze it. At every setup the mean prediction is set
against the mean measured rate, and P6 asks two thirds of setups within 0.67 to 1.5 and a median ratio
of at least 0.8.

| Pair, backend | Setups inside 0.67–1.5 | Median ratio |
|---|---|---|
| Arm, Kafka | 0 of 18 | 2.49 |
| First x86, Kafka | 0 of 61 | 3.24 |
| First x86, Redis | 0 of 43 | 13.08 |

Ten setups measured no negative reading at all, three on Kafka and seven on Redis, all at the two
trips past the cliff; they have no ratio and are listed in the answer. The error has one sign everywhere, and it is
largest where the most threads run: the recording holds every `python3` thread's waits in one
histogram, with no way to tell the thread that stamps "got it" from the sender, the receiver, the
correction thread or, on Redis, sixteen send workers, and most of those waits cannot turn a reading
negative. Version 28 said as much when it added A9, whose recording reads that one thread, message by
message; A9 runs on all three pairs from tonight, and A9-2 and A9-2b are its readings of P6.

An exploratory reading made before version 30, at the trip T rather than T − g, put 7 of 18, 5 of 18
and 2 of 20 setups inside the band (D28-1). T − g is the lower threshold, so it predicts more and sits
further off. The frozen reading is the one that counts.

## What follows

A2's four predictions are judged again once the second Redis day on the HZ=1000 build (complete
tonight, 60 of 60 runs) and the two bridge days are home. The third x86 A3 campaign, A1 on Kafka at 3
and 3.75 ms, A9 and M0 are running or queued on the three pairs, and each is read by the programs
versions 30 and 31 froze before its data exists.

## Pocket dictionary

- **Anchor**: the 3 ms slice every campaign of a block shares, through which each campaign's
  readings are moved by its own offset before the campaigns are compared.
- **Band**: from the slice to one tick past it, where P1, P7 and P9 put the halfway point.
- **Free reading / fitted shape**: the two summaries of one cliff; a prediction needs both.
- **Halfway point**: where the curve crosses midway between its plateau and its floor.
- **Out of reach**: a slice, load or core count the runs cannot test; reported, never counted
  against the law.
- **Plateau**: the share of negative readings on trips shorter than the slice.
- **Resampling whole rounds**: drawing a campaign's rounds again with replacement to get an interval;
  since version 30 each campaign draws from its own rounds (D30-4).
- **T − g**: the trip less the "got it" delay, the margin a wait must outlast for a reading to turn
  negative.
