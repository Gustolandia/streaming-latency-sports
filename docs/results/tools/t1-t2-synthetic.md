# T1 and T2 on made-up tools: what the block could answer before it is run

**20 September 2026. Synthetic, no machines.** Judged against freeze 10 (plan v14),
Section "Experiments for Mode 2 (the industry)".

A pilot tests the instrument and never a prediction; a synthetic run tests the *design* and never
the world. This one asks a question that comes before T1 and T2 are run at all: on the traffic
the block plans to send, could they tell the tool classes apart? A campaign that cannot separate
two behaviours does not give a weak result. It gives none, and it costs the same.

Run with `python3 scripts/tool_synthetic.py report`. Every number below is reproducible from the
committed code at seed 20260920, 3,000 messages, trips about a 3 ms median with a spread of 0.25
on the logarithm — the shape and scale the law campaigns measure on these pairs.

**Words used here.** *Step* — the smallest difference a tool's printing can express; four
decimals of a second is a step of 0.1 ms. *Truncation toward zero* — what integer division does
in Java and C, where these tools are written: a count of nanoseconds divided by a million, so
−0.1 becomes 0 and not −1. *Offset* — how far early T2 makes the receiver's clock read.

## How the made-up tools are built

Each class is built out of the two things that actually make a tool behave as it does, rather
than out of its name:

| | |
|---|---|
| how coarsely its clock reads | a nanosecond, a microsecond, or a whole millisecond |
| whether it reads that clock **once** | it measures the difference in fine units and rounds the answer: at most one step of error, never depending on when the message was sent |
| or **twice** | it reads a coarse clock at each end and subtracts two rounded numbers: up to two steps of error, depending on where in the tick the sending fell |
| what it does with a value at or below zero | keeps it, drops it, drops zero with it, or pulls it up to zero |
| how many digits it prints | |

The same script that judges the real campaign (`scripts/tool_negatives.py`) judges these, against
the same true trips our own program would have recorded. What is reported is the campaign's own
arithmetic on traffic whose answer is known.

## What T1 would find

Sends spread evenly. The smallest added delay each class reports at all, and the furthest its
average sits from the truth across the whole staircase:

| class | smallest step it reports | furthest from the truth |
|---|---|---|
| high, keeps all | 0.1 ms | 0.023 ms |
| medium | 0.1 ms | 0.020 ms |
| low, reads a millisecond clock twice | 0.1 ms | 0.030 ms |
| low, drops the negatives | 0.1 ms | 0.000 ms |
| low, drops zero and below | 0.1 ms | 0.000 ms |
| **low, chops after measuring** | **0.9 ms** | **0.700 ms** |

T1 works as frozen. It separates the class that chops from every other class on the first
question the plan asks of it, and the separation is not marginal: 0.9 ms against 0.1 ms, and an
average 0.7 ms from the truth where the others are within 0.03 ms. That is T-P1 recovered from
a tool's own arithmetic rather than asserted.

## What T2 would find, and why it would not

Whether each class is named from its own figures, at a range of offsets. `--` is a run that did
not answer; **wrong** is a run that named the wrong behaviour.

| class | 0.5 | 2.0 | 3.5 | 4.0 | 5.0 | 6.0 |
|---|---|---|---|---|---|---|
| high, keeps all | -- | named | named | named | named | named |
| low, chops after measuring | -- | -- | -- | -- | named | named |
| low, drops the negatives | -- | -- | named | named | named | named |
| low, drops zero and below | -- | -- | named | named | named | named |
| low, reads a millisecond clock twice | -- | -- | -- | -- | -- | named |
| medium | -- | named | named | named | named | named |

The plan fixes the offsets at **0.5 and 2 ms**. Those are the first two columns.

**At 0.5 ms nothing happens at all.** Against a 3 ms trip, half a millisecond leaves every value
comfortably positive: 0 of 3,000 go below zero. The experiment would have run on every one of the
ten tools, cost what it costs, and asked nothing.

**At 2 ms only the two fine-clocked tools answer.** This is the part that is not obvious. A tool
reading whole milliseconds truncates toward zero, so a trip of 1.9 ms under a 2 ms offset comes
out as 0, not as −0.1. Everything between minus one and plus one lands on zero. Such a tool never
meets a negative, so its rule for negatives never runs — however large the share of trips that
were "really" negative. The offset has to clear the tool's own step before there is anything for
the tool to handle.

Five of the ten tools are in that class. They are the ones the block most wants to characterise.

## Three corrections, all made

1. **The offsets belong to the trip they act on.** At the trip plus three milliseconds every one
   of the six classes is named, and none is named wrongly. At the trip plus one, five of six.
   `scripts/tool_synthetic.py` computes them with `reachable_offsets()`.

2. **The prediction must be made through the tool's own step.** What each behaviour would have
   produced is now worked out from the trips *after* they pass through the step T1 measured,
   because that is what the tool's rule for odd values actually sees. Predicting from the true
   trips instead has the tool dropping values it never saw, and then no behaviour fits what it
   printed. `--step-ms` carries T1's answer into T2.

3. **The verdict is what survives, not what is nearest.** Naming the nearest average was the
   first version, and it was unsound: on a tool whose clock is coarser than the gap between two
   behaviours, the nearest is decided by the rounding rather than by the tool. It named a tool as
   replacing negatives with zero when that tool's clock had erased them before its handling ever
   ran. Each behaviour is now held against every figure the tool printed and ruled out by one it
   cannot account for, with its reason recorded; one left standing is the answer, two are a run
   that did not answer. Where the tool's reading with nothing moved is available — T1's zero step
   — the comparison is on how far each figure *moved*, which cancels the tool's own bias.

## Re-run on trips a campaign actually measured

**21 September 2026.** The table above draws its trips from a lognormal about 3 ms. That was a
guess at the shape, and the shape is the one thing T2 depends on, so it has been replaced by
trips A3's own Kafka campaign measured — 19,952 of them, at 75% load and the 3 ms slice, pooled
over four rounds with each run's first 30 seconds dropped (`data/measured/a3_kafka_trips.json`,
kept as a quantile function rather than twenty thousand numbers).

They are not shaped like the guess:

| | lognormal about 3 ms | what A3 measured |
|---|---|---|
| smallest trip | no floor at all | **2.035 ms** |
| middle | 3.000 ms | 2.686 ms |
| 99th | 5.36 ms | 8.387 ms |
| largest | unbounded | 10.668 ms |

The floor is the part that matters, and it is not an accident of this pair: a message cannot
arrive before the client's own zero-delay trip, which is the same fact version 8 of the plan used
to rule slices out of reach.

**It makes the finding stronger, not weaker.** At the 2 ms offset the plan froze, the lognormal
put 177 of 3,000 values below zero. The measured trips put **none** — not one, because the
shortest trip there is 2.035 ms. The experiment as frozen does not merely under-ask on most of
the tools; on these trips it asks nothing at all, of any of them.

With the offsets version 15 sets — the session's own median trip plus 1 ms and plus 3 ms, which
here is 3.69 and 5.69 ms — five of the six classes are named, and none is named wrongly.

**One class stays out of reach: the tool that reads a millisecond clock twice.** It is named at
6.0 ms and at 7.0 ms and not at 6.5, which is what a marginal result looks like rather than a
threshold. That is the class's own nature: its error depends on where in the tick each message
was sent, so it carries a variance the others do not, and that variance is of the same size as
the difference T2 is trying to see. T2 is therefore expected to report *undecided* for
ProducerPerformance and emqtt-bench, and the prediction about them (T-P2) is judged by T1, which
separates them cleanly. That is recorded here as a limit of the design, before it runs, rather
than discovered afterwards.

## What this does not show

These are made-up tools. They show what the *design* can and cannot resolve, on traffic whose
answer is known; they say nothing about how any real tool behaves, and no prediction is confirmed
or refused by anything here. A class named correctly in this table is a class the experiment
could identify, not one that has been identified.

Two conditions are left open and belong in the campaign rather than here. Sends **paced in step
with the tick** are the adversarial case for the class that reads its clock twice, and the plan
already predicts it (T-P2); in this run that pacing is where the remaining wrong answers sit, so
T2's identification should be taken from the evenly spread condition and the paced one reported
as T-P2's evidence. And an offset can be made **too large**: at the trip plus three, a tool that
drops zero and below with paced sends has nothing left to print at all.

## What this asks of the plan

A new freeze. T2's offsets are frozen at 0.5 and 2 ms, and this result says those cannot answer
the question the block asks — not on the trips these pairs measure. The change is to take the
offsets from the measured trip and to carry T1's measured step into T2's analysis. No machine has
run T1 or T2 yet, so nothing is invalidated; the correction is cheaper now than after.
