# Quiver and the Pravega benchmark through T1 to T4 and S1: freeze 37

Freeze 37 (plan version 40, `freezes/37-experiment-plan`, public as `1a5a2f26` before any judged
run) ran the two tools of the second October reading that build from source on older toolchains,
on the second x86 pair (`matched-b`), four rounds each, on 12 October 2026: Quiver at commit
ba4e5766, built against Qpid Proton C 0.40.0 and run with its qpid-jms arrows against version 39's
Artemis broker, and the Pravega benchmark at its v0.13.0 tag, built with Gradle 4.10.2 on Java 8,
against Pravega 0.13.0's standalone server. Jobs 121 to 171 all finished with status 0; none stopped
on a rule, and none was run again. The runs are home, checked file by file against fingerprints
taken on the pair, in `runs/azure/collected/matched-b/v40_20261012T034644Z` (1,459 files). The
pilots of freezes 36 and 37 are beside them in `pilots_v39_v40_20261012T034708Z` (491 files), and
freeze 35's in `runs/azure/collected/matched/pilots_v38_20261012T022820Z` (91 files).

*Glosses. **T1**, the staircase: a known delay added toward the driver in ten steps. **T2**: the
clock of the process that subtracts moved back by more than the tool's trip. **T3**: idle against
88% load, with and without real-time priority. **S1**: the driver's wall clock stepped back about
five times a second while the tool runs. **Wrap**: an unsigned 64-bit subtraction turning a value
below zero into 2^64 less its size, about 1.8 × 10^19 ms, some 585 million years.*

## The short of it

*In plain words: Quiver's summary turns a value below zero into hundreds of millions of years, and
the Pravega benchmark stops counting at the first one; one prediction failed, for a reason in the
instrument.*

- **S1-q held in all four rounds.** Under the steps Quiver's transfers held 9, 25, 22 and 9 values
  below zero, and its summary's maximum wrapped each time; its controls held none.
- **S1-p held in all four rounds.** The Pravega benchmark printed one window under the steps and
  nothing after it: its one statistics task threw `ArrayIndexOutOfBoundsException` at the first
  value below zero, so no total was printed. Its controls printed their totals.
- **T2-q failed, in round 1 only.** Quiver's maximum wrapped at both offsets in every round, and at
  the larger offset its median and average wrapped too. But T2-q also asked its average to wrap at
  the smaller offset, and in round 1 only 1 of its 3,000 transfers fell below zero there.
  libfaketime, which moves its receiver's clock, slowed the receiver by about a millisecond at an
  offset other than zero, so its usual trip of 1 ms became 2, equal to the offset. In rounds 2 to 4,
  2,308 to 2,992 transfers fell below zero at that offset, and T2-q held.
- **The Pravega benchmark's clock, by the rule, is not the one predicted.** Its figures did not move
  with the clock, but version 34's rule answered two in five of its eight runs, each by its count:
  it counts what arrives in its minute, set-up included, 43 or 44 short of the 3,000 asked for.

## T1, the staircase

| Tool | Figure | Round 1 | Round 2 | Round 3 | Round 4 |
|---|---|---|---|---|---|
| Quiver | median | 1.08 | 1.48 | 1.43 | 0.90 |
| Pravega benchmark | median | 1.09 | 1.14 | 1.14 | 1.03 |

Both inside the band, 0.5 to 1.5, in every round. Quiver's median is whole milliseconds, so its
slope is coarse.

## T2, the moved clock

*In plain words: Quiver's summary went past 10^18 ms whenever enough transfers went below zero; the
Pravega benchmark's figures stayed put while its count misled the rule.*

| Round | Quiver control: below zero, max (ms) | 2 ms: below zero, average (ms) | 4 ms: below zero, average (ms) |
|---|---|---|---|
| 1 | 0, 18 | 1, 6.1 × 10^15 | 2,995, 1.8 × 10^19 |
| 2 | 0, 18 | 2,308, 1.4 × 10^19 | 2,999, 1.8 × 10^19 |
| 3 | 0, 18 | 2,390, 1.5 × 10^19 | 2,999, 1.8 × 10^19 |
| 4 | 0, 19 | 2,992, 1.8 × 10^19 | 2,999, 1.8 × 10^19 |

Every offset run's maximum was 2^64 ms. Version 34's rule answered two in all eight runs, and freeze
21's judge left all eight undecided: none of its five behaviors is a wrap.

Read from its transfers after the runs, Quiver's trip, in whole milliseconds, was 2 ms in 97.3 to
99.8% of the transfers of round 1's two offset runs and of round 3's larger one, and 1 ms or less in
76.9 to 99.97% of those of every other run, its four controls among them. Its reference, timed under
libfaketime at no offset, was 1 ms in every round, so the offsets were 2 and 4 ms in each. A slowed
receiver changed nothing at 4 ms, where a trip of 2 ms still comes out below zero, but at 2 ms in
round 1 it left only 1 transfer below zero.

| Round | Pravega control: count, average (ms) | 2 ms: count, average | 4 ms: count, average | Version 34 |
|---|---|---|---|---|
| 1 | 2,957, 1.0 | 2,956, 1.1 | 4,298, 1.1 | two (count), one |
| 2 | 2,957, 1.2 | 2,957, 1.2 | 2,956, 0.9 | undecided, two (count) |
| 3 | 2,957, 1.2 | 2,956, 1.2 | 2,956, 1.2 | two (count), two (count) |
| 4 | 2,957, 1.1 | 2,957, 1.2 | 2,956, 1.0 | undecided, two (count) |

Its median was 1 ms in every run. Its T2 moved the machine's own clock (the pilots found libfaketime
slowing its JVM). The rule answers one only for a count that is whole, and answers two for a count
shorter than its control's; the benchmark's count is set by time. In round 1's 4 ms run nothing was
printed for 28 s in the middle of the run, after which it counted 4,298 events at 72.7 a second,
its writer catching up past its pace: the one run whose count was whole, and the one the rule
answered one. The two runs it left undecided, round 2's and round 4's at 2 ms, kept 2,957: short of
the 3,000 but not of their controls' 2,957, so the rule could answer neither one nor two.
`tools_t2.csv` gives for them the rule's catch-all reason, that the figures moved between a quarter
and half the offset, though the average moved by 0.1 ms at most and the median not at all.

## T3, the busy machine

Both print whole milliseconds. Quiver's median rose from 1 ms to 2 or 3 under the load and
Pravega's from 1 to 1 or 2, and real-time priority put both back to 1 ms in every round. Quiver's 99th
percentile rose most of any tool in the block, from 1.5 to 8 ms. In round 2 its idle 99th percentile
was 5,994 ms, a stall.

## S1, the stepped clock

| Tool | Round 1 | Round 2 | Round 3 | Round 4 | Controls |
|---|---|---|---|---|---|
| Quiver, transfers below zero | 9 | 25 | 22 | 9 | 0 |
| Pravega, final line printed | no | no | no | no | yes |

Each Pravega stepped run printed the same exception six times, the trace from its main thread and
again from its shutdown hook, each with its causes. S1-p as written also says the program still
exits with status 0, which its source does after printing any exception (`PravegaPerfTest.java:171`,
an unconditional `System.exit(0)` after the `catch` that printed the trace). `s1_block.py` judges
only the missing total and the exception, and the S1 runner did not record the exit status, so
that clause was predicted and not observed; the supplement says so. Every stepped run made between 326 and 343 steps,
and the clock was put back within 0.05 ms of the PTP clock.

## Stalls on the second pair

*In plain words: sometimes nothing arrived for seconds, then everything at once; this did not decide
any verdict, and its cause is not known.*

In some runs nothing reached Quiver's receiver, or the Pravega benchmark's reader, for seconds, after
which what had been held arrived at once: in the pilots, two of Quiver's ten staircase runs, by up to
17.3 s; in the judged runs, among others, Quiver's T1 zero step in round 1 (13.8 s) and its idle T3
cell in round 2, and the Pravega run above (28 s). Their medians did not show them. Their cause was
not read.

## The pilots

Three pilots on 12 October, kept beside the judged runs, tested the instruments; version 40's D40-6
gives what each found. In short: libfaketime slowed both JVMs at an offset other than zero, with or
without the monotonic clock moved, so the Pravega benchmark's T2 moves the machine's clock and
Quiver's reference is timed under libfaketime at no offset; and the stalls above, so both controls
are held only under the wrap. The reference under libfaketime at no offset came out at Quiver's
usual 1 ms, which is why round 1's smaller offset was not long enough.

## Pocket dictionary

- **Arrow**: Quiver's word for one of its sending or receiving programs.
- **Unsigned 64-bit integer**: a whole number that cannot be negative; subtracting a larger one from a
  smaller one wraps round to about 1.8 × 10^19.
- **libfaketime**: a library loaded in front of a program to shift the time it sees.
- **ArrayIndexOutOfBoundsException**: Java's error for reading or writing an array outside its
  length, here at a negative index, the value below zero.
- **Count clause**: the part of version 34's rule that answers two when a tool kept fewer values than
  it was asked to publish and than its control kept.
