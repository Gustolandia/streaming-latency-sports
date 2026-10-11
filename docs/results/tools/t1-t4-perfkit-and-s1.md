# PerfKit Benchmarker through T1 to T4, and S1: what four one-clock tools do with a value below zero

First x86 pair (`matched`), 11 October 2026, under plan version 37 (`freezes/34-experiment-plan`,
public as `58d6f46d` before any judged run). PerfKit Benchmarker's messaging benchmark (commit
e5fd49d7, azure-servicebus 7.15.0) ran T1 to T4 against an Azure Service Bus queue of the Standard
tier made for it, four rounds, and S1, the step test, ran on five tools in the same four rounds:
38 jobs (302 to 339), every run read, none stopped and none run again. The judged block's install
found PerfKit already laid out by the pilot, whose `commit_pkb.txt` and `pkb_packages.txt` record
that commit, read back by git, and that package. The runs are home, checked file by file against
the fingerprints taken on the pair, in `runs/azure/collected/matched/v37_20261011T142007Z` (489
files, besides the archive and its fingerprints); the three pilots that preceded the freeze are
beside them, in `pilots_v37_20261011T142023Z` (147 files). The queue's resource group was deleted
once the runs were home, and the pair stopped itself.

*Glosses. **T1**, the staircase: a known delay added to the path in steps; it delays the broker's
traffic toward the driver, so it cannot reach a managed queue's path, and PerfKit's T1 is its zero
step alone. **T2**: the clock of the process that subtracts moved back by more than its trip.
**T3**: idle against 88% load, with and without go-first. **T4**: what the tool can report.
**S1**: the driver's wall clock stepped back while the tool runs, chrony stopped; a message still
on its way when the clock steps back is timed short by the step, and so comes out below zero if
the step is longer than its trip. **One clock**: both timestamps read from one clock,
in one process or in two on one machine.*

## The short of it

- **S1: every prediction held in all four rounds.** Stepped back by 20 ms (50 ms for PerfKit) at
  gaps drawn around a fifth of a second, PerfKit kept the values below zero in its samples, mean
  and percentiles (8 to 18 a run); Strimzi Canary logged them (10 to 20); Stream PerfTest, as one
  instance, dropped them, uncounted (16 to 25); and Xinfra Monitor's metrics library pinned them to
  its percentiles' floor (40 to 84), which only its debug line shows: its printed 99th percentile
  read 2 ms in every stepped run, as in every control. No control showed one. Kafka's end-to-end
  tool, on a monotonic clock, did not see the steps.
- **PerfKit times against one clock, as predicted.** Its publisher and receiver are two processes
  of one program on the driver; T2's offset moved both, and version 34's answer from the offset
  alone is one clock in all eight runs, each keeping 100 of 100 messages. Freeze 21's judge left
  all eight undecided: its allowance for noise comes from the staircase PerfKit does not have.
- **PerfKit's figures.** Its median trip to the queue was 21 to 23 ms in every T1 and T4 run; its
  maximum, 507 to 555 ms in every run without steps, is its first message's in each. T3 cannot be
  read for it: its 99th percentile of 100 messages is the queue's own tail.

## S1, round by round

Values below zero each tool's own output showed (`s1.csv`, judged by `scripts/s1_block.py`).

| Tool | Step | Round 1 | Round 2 | Round 3 | Round 4 | Controls |
|---|---|---|---|---|---|---|
| PerfKit, samples below zero | 50 ms | 8 | 18 | 10 | 18 | 0 |
| Strimzi Canary, durations logged below zero | 20 ms | 13 | 20 | 16 | 10 | 0 |
| Stream PerfTest, latencies not kept | 20 ms | 16 | 21 | 18 | 25 | 0 |
| Xinfra Monitor, values pinned to the floor | 20 ms | 45 | 84 | 40 | 60 | 0 |
| Kafka's end-to-end tool, p50/p99 in ms, stepped vs control | 20 ms | 1/3 vs 1/4 | 1/2 vs 1/2 | 1/2 vs 1/2 | 1/2 vs 1/2 | — |

A stepped run made 302 to 517 steps, the number set by how long the tool runs; Kafka's end-to-end
tool, done in seconds, took 29 to 33. Each step landed within 1.7 ms of the step asked, and in all
but two runs within 0.06 ms (S1-a allows 5). The steps were then undone, the clock set forward
by what the PTP clock measured they took, and it ended within 0.09 ms of the PTP clock (S1-a,
every run). PerfKit's negatives ran
from −31 to −3 ms, its trip less the 50 ms step; its printed mean equals the mean of all its
samples, negatives included, in every round. In round 1's stepped run its first message took
4,123 ms by its own clock, against 341 to 420 ms in the other three, so that run's mean, 63.5 ms,
stands apart; the count of values below zero does not rest on it.

## PerfKit's T2 and T3

| Round | Offsets (ms) | Kept | Version 34 | Freeze 21 |
|---|---|---|---|---|
| 1 | 24.02, 26.01 | 100, 100 | one, one | undecided, undecided |
| 2 | 23.50, 25.58 | 100, 100 | one, one | undecided, undecided |
| 3 | 22.99, 25.00 | 100, 100 | one, one | undecided, undecided |
| 4 | 22.01, 24.00 | 100, 100 | one, one | undecided, undecided |

Its median moved by at most 2 ms and its average by at most 3.9 ms against offsets of 22 to 26 ms.
In T3 its median stayed at 21 to 23.5 ms in every cell, and its 99th percentile ran from 80 to
247 ms, swinging by some 140 ms between idle rounds alone; T3's figures describe it apart, as they
describe the Yahoo Streaming Benchmark, whose figure is set by its flush.

## The pilots

Three pilots on 11 October, before the freeze, are kept as `pilot_v37` to `pilot_v37c` beside the
judged runs. They tested instruments, never a prediction, and none of their runs is in a figure
above. D37-5 gives what each found; in short:

- Steps exactly once a second met the canary's and Stream PerfTest's 20 ms send timers at the same
  moment of their cycle, between two messages, so neither showed a value below zero, while
  PerfKit, whose sends are not on a timer, printed two (−29 and −14 ms). The judged runs draw the
  gaps, about five steps a second.
- Xinfra Monitor's debug line went to the log file every run shares, through the logger it
  inherited; it now has a console of its own.
- After 509 steps the clock, set forward by the steps asked, was up to 5 ms behind the PTP clock,
  because each step lands a few microseconds late; it is now set forward by what the PTP clock
  measured. The third pilot checked both changes: Xinfra Monitor's console carried 58 pinned
  values and its control's none, and the clock came back within 0.05 ms.
