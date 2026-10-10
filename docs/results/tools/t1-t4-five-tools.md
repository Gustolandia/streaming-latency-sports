# T1–T4, the five tools freeze 30 added: all five measure the path, three span two clocks

First x86 pair (`matched`), 9–10 October 2026, under plan version 33 (`freezes/30-experiment-plan`,
public as `c9389343` before any judged run). Four rounds of T1 to T4 for each of the five tools the
plan registered and version 15 left unrun: the OpenMessaging Benchmark (`omb`), Apache Pulsar's
performance client (`pulsar-perf`), emqtt-bench, YCSB and nats bench. 80 jobs, 360 runs, every run
read; none stopped and none was run again. The runs are home, checked file by file against the
fingerprints taken on the pair, in `runs/azure/collected/matched/v33_20261010T075920Z` (2,526
files); the pilot and the shakedown that preceded the freeze are beside them
(`pilot_v33_20261009T203142Z`, `shakedown_v33_20261009T213112Z`). The pair stopped itself when
the runs were home.

*Glosses. **T1**, the staircase: a known delay added to the path in ten steps, 0 to 2 ms, asking
how far each tool's figure moves. **T2**, forced negatives: the clock the tool's subtracting process
reads is moved back by more than its trip, and the question is what it does with a result below
zero. **T3**: idle against 88% load, with and without go-first. **T4**: what the tool can report at
all. **Two clocks**: the tool's two timestamps are taken by two processes, so moving one process's
clock moves the difference, the arrangement in which a value below zero can arise.*

## The short of it

- **Every tool's figure follows the delay.** All twenty staircases measured the path (D25-5),
  each crossing the delayed direction once as the freeze's addendum predicted.
- **Two of the five time against one clock, as predicted: YCSB and nats bench.** Moved back by
  their trip plus one and plus three milliseconds, their figures did not move: 15 of their 16
  offset runs were judged "times against one clock", the 16th undecided.
- **Three span two clocks, as their invocations predicted: OMB, pulsar-perf and emqtt-bench.**
  In every one of their 24 offset runs their figures moved with the clock, or, where a filter
  dropped everything, nothing was left to print. emqtt-bench's histogram
  went below zero, and the rule judged it "keeps every value" in 5 of its 8 offset runs, as its
  source says. OMB and pulsar-perf dropped what went below zero: OMB's median fell from 2 ms to the
  1 ms its surviving values held, or it printed nothing at all; pulsar-perf kept 3 to 7 of its
  3,000 latencies at the larger offset. The frozen rule did not decide either tool's behaviour
  (15 undecided of 16), and once, for pulsar-perf, it returned "times against one clock" for a run
  that kept 7 of 3,000 (below).
- **With these five, 12 of the 16 tools run time both ends in one process** (the eleven's ten, YCSB
  and nats bench) and **4 span two processes** (rdkafka\_performance, OMB, pulsar-perf, emqtt-bench).
- **Freeze 31 judged every T2 run of both blocks again** (below). Its corrected rule changes two
  verdicts, both pulsar-perf's, and its clocks answer, read from the offset itself, puts each of
  the 16 tools on one clock or on two exactly as its invocation was read: one in 96 of 96 runs of
  the twelve, two in 29 of 32 runs of the four, the other three undecided.

## T1: the staircase

Slope of the figure the staircase was read on, per millisecond added, by round. The band fixed in
advance is 0.5 to 1.5 for one crossing.

| Tool | Figure | Round 1 | Round 2 | Round 3 | Round 4 |
|---|---|---|---|---|---|
| omb | median | 1.036 | 1.000 | 0.843 | 0.557 |
| pulsar-perf | median | 1.029 | 1.029 | 1.141 | 1.141 |
| emqtt-bench | average | 0.914 | 0.947 | 0.903 | 1.052 |
| ycsb | median | 1.007 | 1.014 | 1.003 | 1.039 |
| nats-bench | median | 1.026 | 1.018 | 1.023 | 1.001 |

OMB's median is a whole number of milliseconds, so its staircase is a few one-millisecond steps and
its slope moves from round to round with where those steps fall; round 4's 0.557 is inside the
band, near its edge. emqtt-bench is read on its average because it prints no percentile.

emqtt-bench's staircase also shows the pattern T-P2 predicts for sends paced in step with the
clock's tick (D15-4). Its publisher sends on a whole-millisecond timer, so within a run every
message meets the clock's millisecond at the same phase, and every latency in a run takes the same
whole value: its round-1 averages read 1.000 at 0, 0.1, 0.2 and 0.3 ms added, 2.000 at 0.5,
1.251 at 0.7, 2.000 at 1.1 and 1.5, and 3.001 at 2.0. In one control run (round 2) every one of
its 3,000 messages read 0 ms: its histogram's sum was 0.

## T2: forced negatives

Each tool's figure in the control run (no offset) and in its two offset runs, with the verdict of
the rule frozen in version 21 (D25-2, D26-2). "Kept" is the tool's own count of what it recorded,
where it gives one.

| Tool | Round | Control | First offset | Second offset |
|---|---|---|---|---|
| omb | 1 | median 2.0 | 2.74 ms: median 1.0 — undecided | 4.74 ms: median 21.0 — undecided |
| omb | 2 | median 2.0 | 2.99 ms: median 6.0 — undecided | 4.99 ms: median 11.0 — undecided |
| omb | 3 | median 2.0 | 2.66 ms: median 1.0 — undecided | 4.66 ms: nothing recorded — undecided |
| omb | 4 | median 2.0 | 2.68 ms: median 1.0 — undecided | 4.68 ms: median 11.0 — undecided |
| pulsar-perf | 1 | avg 3.14, kept 3,001 of 3,001 | 3.04 ms: avg 0.22, kept 3,000 — undecided | 5.04 ms: kept 7 of 3,000 — **times against one clock** |
| pulsar-perf | 2 | avg 3.24, kept 3,000 | 3.03 ms: avg 0.26, kept 3,000 — undecided | 5.03 ms: kept 7 of 3,000 — undecided |
| pulsar-perf | 3 | avg 3.15, kept 3,000 | 3.03 ms: avg 0.22, kept 3,000 — undecided | 5.03 ms: kept 3 of 3,000 — undecided |
| pulsar-perf | 4 | avg 3.24, kept 3,000 | 2.98 ms: avg 0.22, kept 3,000 — undecided | 4.98 ms: kept 4 of 3,000 — undecided |
| emqtt-bench | 1 | avg 1.0 | 1.67 ms: avg −1.0 — undecided | 3.67 ms: avg −3.0 — keeps every value |
| emqtt-bench | 2 | avg 0.0 | 1.66 ms: avg −1.0 — undecided | 3.66 ms: avg −3.0 — keeps every value |
| emqtt-bench | 3 | avg 1.0 | 1.68 ms: avg −1.0 — undecided | 3.68 ms: avg −2.99 — keeps every value |
| emqtt-bench | 4 | avg 1.0 | 1.60 ms: avg −1.0 — keeps every value | 3.60 ms: avg −2.26 — keeps every value |
| ycsb | 1–4 | median 0.66–0.70 ms | moved ≤ 0.06 ms — one clock in 3 of 4, undecided in 1 | moved ≤ 0.08 ms — one clock in 4 of 4 |
| nats-bench | 1–4 | median 1.17–1.41 ms | moved ≤ 0.07 ms — one clock in 4 of 4 | moved ≤ 0.24 ms — one clock in 4 of 4 |

What the figures show, rule aside:

- **OMB** drops every difference at or below zero. At the first offset most messages computed to
  zero or below and only those that had taken longest were kept, so its median fell to 1 ms, or,
  where the survivors were the slow tail alone, rose; at the second offset only the tail survived
  or, in round 3, nothing did, and the reader recorded no figure rather than the zeros an empty
  histogram reports.
- **pulsar-perf** drops a negative and keeps a zero. At the first offset nothing went below zero —
  its trips are a little longer than the offset, so the stamps' difference read mostly 0 or 1 —
  and it kept all 3,000; at the second, it kept 3 to 7 of 3,000, the rest dropped and counted
  nowhere but in its own histogram file.
- **emqtt-bench**'s histogram kept every value, its sum going below zero with the clock. Its
  console said nothing at all: its once-a-second average is printed only when a counter that adds
  latencies above zero changes, and under either offset it never did, so no latency line appeared
  in any of its eight offset runs.

## Where the frozen rule and the figures part

The freeze said its verdicts would be read as written, beside the figures and the counts, and
named the two ways its model and these tools differ (its addendum, "What T2's judge assumes").
Both appeared, and a third:

1. **A short count is not held against "times against one clock"** (D26-2 rules out only the
   behaviours that keep every value). A tool on one clock keeps every value as well, so pulsar-perf
   round 1, keeping 7 of 3,000, had every other hypothesis ruled out and that one left standing.
2. **The predictions come from our reference's trips, not the tool's.** Our Pulsar client's trips
   have no long tail, so at 5 ms every dropping behaviour was predicted to leave nothing to print,
   and was ruled out when pulsar-perf printed the seven it kept from its own slow tail.
3. **OMB's figures are hard for the rule to judge.** In rounds 1 and 3 a few slow messages a run
   (up to 63 ms) put the noise of its average near 10 ms, so its allowance was about 40 ms; in
   rounds 2 and 4 the allowance was under 2 ms, and no hypothesis survived, because of point 2. Its
   minimum, in whole milliseconds, is allowed two of them; its median, which moved every time, is
   not one of the figures T2 judges.

None of this is corrected in the verdicts above. A correction had to be a new freeze, applied to
every T2 run of both blocks, with both verdicts reported, as version 21 did for its own (D25-2);
freeze 31 is that correction, and the next section reports it.

## Judged again under freeze 31

Plan version 34 (`freezes/31-experiment-plan`, public as `c17b3650` on 10 October before either
block was judged again) corrects the first of the three points: a short count is now held against
"times against one clock" too (D34-1). The other two stay limits of the judgement, recorded as
such (D34-4). It also asks T2's first question, how many clocks a tool's two timestamps come from,
from the offset itself rather than from our reference's trips (D34-2):

- **two** where the tool kept fewer values than it was asked to send, and fewer than its control
  kept, or where its average, median or minimum moved by more than half the measured offset;
- **one** where every one of them moved by less than a quarter of the offset and it kept every
  value;
- **undecided** otherwise.

Every T2 run of both blocks was judged again under both (D34-3) by `scripts/tools_block.py`. It
first judges each run again under freeze 21, from the inputs the run left, and stops if that does
not give the verdict the run was given; all 128 reproduced. `docs/results/tools/tools_t2.csv`
carries each run's verdict as given, its freeze-31 verdict (`verdict_31`) and its clocks answer
with the reason (`clocks`, `clocks_why`).

| Block | Runs | Freeze 21 verdicts | Freeze 31 verdicts | Clocks |
|---|---|---|---|---|
| the eleven | 88 | 70 one clock, 6 keeps every value, 12 undecided | the same | 80 one, 8 two |
| the five | 40 | 16 one clock, 5 keeps every value, 19 undecided | 15 one clock, 5 keeps every value, 1 drops the negatives, 19 undecided | 16 one, 21 two, 3 undecided |

Two verdicts change, both pulsar-perf's at the larger offset. Round 1's "times against one clock"
becomes undecided, and round 2's undecided becomes "drops the negatives", because the count now
rules out the one-clock hypothesis, the other one left standing there.

The clocks answer, by tool:

- **One, in every run:** the eleven's ten, YCSB and nats bench, 96 of 96 runs.
- **Two:** rdkafka\_performance, emqtt-bench and pulsar-perf in all 8 runs each, and OMB in 5 of
  8, 29 of 32 runs in all. OMB's other three, at the first offset of rounds 1, 3 and 4, are
  undecided: its median fell by 1 ms, from 2 ms to 1 ms, against offsets near 2.6 ms, between a
  quarter and half of the offset.

Every tool is answered one way only, and the way its invocation was read before any run: the four
answered "two" are the four whose invocations time across two processes.
`scripts/emit_paper_numbers.py` refuses to build the paper's numbers if either stops being so, or
if any run of a one-clock tool is answered anything but "one".

## Faults and departures

- **OMB's workers could not write their own log file in T2.** T1, T3 and T4 run the tool as root in
  the receiver's namespace, and the first run left `benchmark-worker.log` owned by root in the
  benchmark's folder; T2 runs it as the user on the machine itself, and its log4j could not open the
  file (`Permission denied`). The workers ran and reported; no figure comes from that file.
- **The driver ran kernel 6.8.0-1065-azure**, as it did for the eleven's rounds of 25 September
  (the queue's log records the kernel at every job).
- **Cost:** the pair ran about 11.5 hours for the pilot, the shakedown and the block, about EUR 5 at
  list price.
