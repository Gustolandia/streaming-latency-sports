# Seven more tools through T1 to T4, and four more in S1: freezes 35 and 36

Freeze 35 (plan version 38, `freezes/35-experiment-plan`, public as `a2ecdfd4` before any judged
run) ran four tools of the second October reading on the first x86 pair (`matched`): mqtt-benchmark,
IBM Sarama's producer tool, SBK and Redpanda's kgo-repeater. Freeze 36 (plan version 39,
`freezes/36-experiment-plan`, public as `05da5803`) ran three on the second x86 pair
(`matched-b`): Apache Artemis's perf client, RocketMQ's benchmark and BookKeeper's benchmark, each
against a broker of its own started alone on the broker machine. Both ran on 11 October 2026, four
rounds each: freeze 35 as jobs 341 to 422 and freeze 36 as jobs 52 to 120. Every job finished with
status 0, none stopped on a rule, and none was run again. The runs are home, checked file by file
against fingerprints taken on each pair: `runs/azure/collected/matched/v38_20261011T234032Z`
(1,870 files) and `runs/azure/collected/matched-b/v39_20261011T232744Z` (1,889 files).

*Glosses. **T1**, the staircase: a known delay added to the broker's traffic toward the driver, in
ten steps from 0 to 2 ms; a tool that measures the path moves its figure with it. **T2**: the clock
of the process that subtracts moved back by more than the tool's trip, to see what the tool does
with a value below zero. **T3**: the tool idle and against a load keeping every core 88% busy, with
and without real-time priority. **T4**: what the tool can report at all. **S1**: the driver's wall
clock stepped back about five times a second while the tool runs. **One clock / two clocks**:
whether the tool's two timestamps are read from one clock or from two.*

## The short of it

*In plain words: most predictions held; two failed, and each failure is reported as a failure.*

- **Held.** Artemis's consumer refuses a value below zero and has the message delivered again
  (T2-a); RocketMQ's average falls by the offset (T2-r); BookKeeper's median carries its own rate
  limiter's wait (T4-b); Artemis's producer stops short under the steps and still says success
  (S1-k); SBK counts the values the steps make (S1-g); mqtt-benchmark never meets one (S1-h). Each
  held in all four rounds.
- **Failed: RocketMQ's T1.** Its B2C average did not follow the staircase in any round: slopes of
  4,058, 4,375, 900 and 1.78 ms per millisecond added, against a band of 0.5 to 1.5. Read after the
  runs, some runs waited about 20 s in the broker before the consumer was given its queue, and the
  rest rose by about two crossings, not one. The section below gives the reading.
- **Failed: S1-i on Sarama's tool.** Its median under the steps matched its control's in every
  round, but its 99th percentile fell 1.3 to 3.8 ms *below* its control's, outside the millisecond
  the rule allowed. Its clock is monotonic, so the steps cannot reach it; the tolerance was narrower
  than its 99th percentile's spread from one run to the next.
- **Not predicted, and reported: Artemis's clock count.** Artemis's perf client subtracts across
  two processes, but its redeliveries keep the offset out of its figures, so version 34's rule
  answered one (five runs) or undecided (three), never two. Version 39 declined to predict that
  answer for this reason.
- **One undecided run among the one-clock tools.** SBK's minimum, printed in whole milliseconds,
  moved by one at round 3's smaller offset, more than a quarter of it.

## T1, the staircase

*In plain words: every tool but RocketMQ's moved its figure by about one millisecond per
millisecond added.*

| Tool | Figure | Round 1 | Round 2 | Round 3 | Round 4 |
|---|---|---|---|---|---|
| mqtt-benchmark | average | 1.00 | 1.01 | 1.00 | 1.01 |
| Sarama's producer tool | median | 1.28 | 1.27 | 1.34 | 1.01 |
| SBK | median | 0.67 | 0.91 | 0.58 | 0.61 |
| kgo-repeater | median | 0.99 | 1.06 | 1.09 | 0.97 |
| Artemis perf | median | 0.97 | 0.96 | 1.06 | 1.04 |
| RocketMQ benchmark | average | 4,057.78 | 4,375.24 | 899.73 | 1.78 |
| BookKeeper benchmark | median | 0.73 | 0.87 | 1.14 | 1.20 |

### RocketMQ's staircase, read after the runs

*In plain words: in some runs the messages sat in the broker for twenty seconds, waiting for the
consumer to be told where to read; in the rest, the consumer met the delay twice per message.*

`scripts/rocketmq_post_hoc.py` reads every RocketMQ run, each round's reference run among them, into
`rocketmq_waits.csv` and `rocketmq_t1.csv`. Its producer has no rate of its own: one thread sends
and waits for each reply, so it sends 3,000 messages in about three seconds. Its consumer starts ten
seconds earlier, on a topic made for the run, and is given the topic's queue only when its client
next balances its queues, every 20 s (`RebalanceService.java:25-27` at 5.5.1). Six of the 76 runs
waited: five staircase steps averaged 19.4 to 20.3 s, and round 4's reference run 139 ms. In each,
the store-to-consumer time it also prints was within a millisecond of the whole, so the wait came
after the broker stored the messages. No run that did not wait averaged more than 5.2 ms. Without
the runs that waited, the staircase still rose 1.78 to 2.04 ms per millisecond added, and the
store-to-consumer time 1.63 to 1.97, which leaves the producer out. The consumer pulls: it asks
the broker for messages and asks again when the answer comes, so a message stored just after an
answer has left waits for the next request, which follows that answer across the delay. The
prediction counted one crossing where the consumer makes about two.

Round 4's reference run is the one that set that round's T2 offsets, 139.92 and 141.93 ms against
2.35 to 4.81 ms in the others. T2-r held there too.

## T2, the moved clock

*In plain words: the one-clock tools did not move; kgo-repeater and RocketMQ moved by the offset;
Artemis could not show it.*

| Tool | Round | Offsets (ms) | Version 34 | What moved (version 34) |
|---|---|---|---|---|
| mqtt-benchmark | 1–4 | 1.61 to 3.72 | one in all 8 | mean and minimum by at most 0.03 ms |
| Sarama's producer tool | 1–4 | 2.70 to 4.86 | one in all 8 | median 0; mean by at most 0.5 ms |
| SBK | 1–4 | 2.63 to 4.72 | one in 7, undecided in 1 | round 3 at 2.69 ms: minimum −1 ms |
| kgo-repeater | 1 | 2.69, 4.70 | two, two | median −2.70, −4.82 ms |
| kgo-repeater | 2 | 2.72, 4.72 | two, two | median −2.64, −4.69 ms |
| kgo-repeater | 3 | 2.64, 4.64 | two, two | median −2.69, −4.75 ms |
| kgo-repeater | 4 | 2.69, 4.69 | two, two | median −2.73, −4.72 ms |
| Artemis perf | 1 | 1.92, 3.93 | undecided, one | median −0.87, −0.63 ms |
| Artemis perf | 2 | 2.04, 4.01 | undecided, one | median −0.96, +0.12 ms |
| Artemis perf | 3 | 1.90, 3.91 | one, undecided | median −0.32, +1.44 ms |
| Artemis perf | 4 | 1.97, 4.01 | one, one | median −0.22, −0.28 ms |
| RocketMQ benchmark | 1 | 2.77, 4.81 | two, two | average −2.73, −4.98 ms |
| RocketMQ benchmark | 2 | 2.35, 4.34 | two, two | average −2.38, −4.22 ms |
| RocketMQ benchmark | 3 | 2.46, 4.49 | two, two | average −2.65, −4.88 ms |
| RocketMQ benchmark | 4 | 139.92, 141.93 | two, two | average −140.14, −141.77 ms |
| BookKeeper benchmark | 1–4 | 26.03 to 28.74 | one in all 8 | median by at most 0.70 ms |

- **kgo-repeater** keeps every value: its median fell by the offset in every run, below zero once the
  offset passed its trip, across two machines.
- **Artemis's perf client** received 5,992 to 8,972 messages for the 3,000 sent at the offsets,
  logged 2,992 to 5,972 AMQ132001 warnings, and reported success, in every round (T2-a,
  `v39.csv`). Its controls received exactly 3,000 and logged none. Freeze 21's judge read one of its
  runs as "replaces the negatives with zero", a decided verdict that the redeliveries explain:
  each refused message came back until it landed at or a little above zero.
- **RocketMQ's** average fell by the offset in every round (T2-r). Its maximum, which starts at zero
  and rises only past it, cannot show a value below zero, and showed 0 in round 4's runs.
- **BookKeeper's** offsets were 26 to 29 ms because its trip includes its rate limiter's wait, a
  fiftieth of a second at 50 adds a second; its median was 25.4 to 25.9 ms in every round's T4 run,
  above the 15 ms predicted (T4-b).

## T3, the busy machine

*In plain words: under load, every tail lengthened; SBK's median also rose, and real-time priority
put it back.*

SBK's median, in whole milliseconds, was 5 ms idle in every round and 6, 7, 6 and 9 ms under the
load; at real-time priority it was 5 again in every round. In round 2 its 99th percentile under the
load was 2,000 ms. Of the other new tools that print a median, none moved it by more than
0.23 ms (Artemis's).

## S1, the stepped clock

*In plain words: SBK counted what the steps made; the two monotonic tools did not see them; Artemis's
producer stopped.*

| Tool | Round 1 | Round 2 | Round 3 | Round 4 | Controls |
|---|---|---|---|---|---|
| SBK, latencies called invalid | 58 | 55 | 35 | 26 | 0 |
| mqtt-benchmark, mean stepped vs control (ms) | 0.66 vs 0.67 | 0.67 vs 0.67 | 0.67 vs 0.68 | 0.68 vs 0.68 | — |
| Sarama, p99 stepped vs control (ms) | 2.5 vs 6.3 | 2.5 vs 5.5 | 2.5 vs 4.5 | 2.5 vs 3.8 | — |
| Artemis, messages its producer sent | 3 | 3 | 10 | 2 | 3,000 |

SBK's median rose under the steps as well, from 5 ms in its controls to 18 to 26 ms, as in its
pilot; why was not read. Every stepped run made between 297 and 466 steps, each landing within
5 ms of the step asked, and the clock was put back within 0.06 ms of the PTP clock.

## Pocket dictionary

- **B2C / S2C**: RocketMQ's two latencies, from the producer's stamp (born) or from the broker's
  store to the consumer.
- **Redelivery**: the broker sending a message again after the client rolled it back.
- **Rebalance**: a RocketMQ client deciding which of a topic's queues each consumer reads.
- **Rate limiter**: BookKeeper's client making each add wait for a permit, here fifty a second.
- **Monotonic clock**: a clock that only moves forward and that a step of the wall clock cannot
  move.
- **Version 34's rule**: the answer, one clock or two, read from how far the tool's figures moved
  under the offset (D34-2).
