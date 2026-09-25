# T1–T4, eleven tools: all eleven measure the path, and ten time against one clock

First x86 pair (`matched`), 23–25 September 2026. The whole tools block — T1 to T4 for each of
the eleven tools — as it stands after the corrections of 24 and 25 September, judged under freeze
21. `rdkafka_performance` has two pages of its own: the [shakedown](rdkafka-shakedown.md) that got
its consumer reading, and [its T1](t1-rdkafka-precision-without-accuracy.md), which found it
reporting half a second for a 2.5 ms trip. What is set out here is the other ten beside it.

*Glosses. **T1**, the staircase: a known delay added to the path in ten steps, 0 to 2 ms, asking
how far each tool's figure moves. **T2**, forced negatives: the clock the tool reads is moved back
further than its trip, and the question is what it does with a result below zero. **T3**: the same
tool on an idle machine and on one kept 88% busy, with and without go-first priority. **T4**: what
the tool can report at all. **Reference**: our own client on the same path, which is what each
tool's number is read against.*

## The short of it

- **Every tool's figure follows the delay one for one.** Fitted over its T1 staircase, each moves
  0.98 to 1.14 ms per millisecond added, and the two tools whose timed interval crosses the delayed
  direction twice move 1.96 and 2.03. None lies outside the half-to-one-and-a-half band freeze 21
  fixed in advance (D25-5).
- **Ten of the eleven time against one clock**, which is what the plan's own reading of their
  invocations predicted on 22 September (the addendum of freeze 21, *How each tool keeps time*).
  Moved back by their median trip plus 3 ms, their figures did not move beyond their own noise.
  A tool like that cannot produce a negative latency, and it cannot measure a one-way trip either.
- **The eleventh, `rdkafka_performance`, spans two clocks**, as that same reading predicted. Its
  figures moved by the offset: its average by −5.42 ms where the offset was 5.48. Which of two
  rules it applies to a value below zero is not decided. Its own noise is 1.1 ms, and freeze 21
  said before the reading that this would leave it undecided.
- **At 88% load nothing moved beyond its own noise, with one marginal exception**: `wrk2`
  under go-first. T3 has no rule fixed in advance, so this is description, not a verdict.

*Glosses. **Crossings**: how many times the interval a tool times passes through the direction
the delay was added to. A round trip meets it once; a message that is sent, acknowledged and then
read back meets it twice. **One clock**: the tool writes both of the timestamps it subtracts
itself, so moving its clock moves both and the difference stays the same. **Noise**: how much a
tool's figure varies from one run to the next with nothing changed.*

## What ran

Each tool was run as its own documentation runs it, at 50 messages or requests a second for 60
seconds, on the driver, against the broker across the pair (`cloud/azure/tools_run.sh`). Their
builds and versions are recorded in `installed.json`, `commit_*.txt` and `version_*.txt` beside
the runs. In brief: valkey-benchmark 9.1.2 (git 7f1dffed), memtier_benchmark at 5694a3d6, the
Kafka 3.7.1 tools on OpenJDK 11, librdkafka at 6f86c853, wrk2 at 44a94c17, PerfTest at ba718d2e,
the nats CLI v0.5.0 against nats-server v2.15.0, and vegeta, hey and k6 at the commits their Go
pseudo-versions name: cf5811269046, 5626f79b8698 and 3fcf5388d78c.

The reference for five tools is our own Redis or Kafka client. The other six had none until 25
September, and each was given a client of our own made for it:
`scripts/http_reference.py` for the four HTTP tools, `scripts/amqp_reference.py` for PerfTest and
`scripts/nats_reference.py` for nats-latency. Each timed 5,000 trips of the 6,500 it sent, with
none lost, at the zero step of the staircase its tool had already run.

*Glosses. **Driver**: the machine the tools run on. **Broker**: the machine the servers they talk
to run on. **Zero step**: the staircase's first rung, with nothing added.*

## T1: does the figure follow the path?

| tool | our reference (median trip) | the tool at no added delay | slope | crossings | its step | smallest step it showed |
|---|---|---|---|---|---|---|
| `valkey-benchmark` | 0.812 ms | p50 0.471 ms | 0.979 | 1 | 0.001 ms | 0.1 ms |
| `memtier_benchmark` | 0.815 ms | p50 0.727 ms | 1.002 | 1 | 0.00001 ms | 0.1 ms |
| `kafka-producer-perf` | 2.256 ms | p50 1.000 ms | 1.141 | 1 | 1 ms | 0.9 ms |
| `kafka-end-to-end` | 2.395 ms | p50 1.000 ms | 2.028 | 2 | 1 ms | 0.7 ms |
| `rdkafka_performance` | 2.493 ms | avg 510.7 ms | 1.958 | 2 | 0.01 ms | 0.1 ms |
| `wrk2` | 0.827 ms | p50 1.460 ms | 1.008 | 1 | 0.01 ms | 0.1 ms |
| `rabbitmq-perftest` | 0.884 ms | p50 0.839 ms | 0.995 | 1 | 0.001 ms | none found (it prints no average) |
| `vegeta` | 0.814 ms | p50 0.764 ms | 1.003 | 1 | 0.000001 ms | 0.1 ms |
| `hey` | 0.805 ms | p50 0.800 ms | 1.038 | 1 | 0.1 ms | 0.2 ms |
| `k6` | 0.821 ms | p50 0.722 ms | 1.011 | 1 | 0.00001 ms | 0.1 ms |
| `nats-latency` | 0.745 ms | p50 0.696 ms | 0.991 | 1 | 0.001 ms | none found (it prints no average) |

The slope is the question T1 asks, and every tool answers it: each one's figure rises with the
delay at the rate its crossings predict. The level at zero is a separate matter and is not the
same trip for every tool. `kafka-producer-perf` times a send to the broker's acknowledgement where
our client times a message all the way to its reader. `rdkafka_performance` reports its own
one-second batching. `wrk2` sits 0.63 ms above our client, because by design it times each request
from when its schedule said the request should go, so any wait before sending is in its figure.
`kafka-end-to-end` averages 1.58 ms where our Kafka client's median is 2.40, and its median is
chopped to a whole millisecond. That is its own Java producer and consumer in one process against
our client, and it is not looked into further here. The other seven sit within 0.35 ms of our
client, all of them below it.

hey's row is read with the reader corrected on 25 September, below. Until then no percentile of
hey's had been read from any run, and its slope was taken on its average: 1.054, where its median
gives 1.038.

Two of these steps are coarse because of how a tool prints. The Kafka tools give their
percentiles in whole milliseconds and their averages finely, and a tool reading a millisecond
clock never shows a delay smaller than its step on the figure that is chopped.

*Glosses. **Slope**: the milliseconds a tool's figure moves for each millisecond the staircase
adds. **p50**: the median. **Step**: the smallest change the tool's printout can show. **Smallest
step it showed**: the smallest added delay the tool's average visibly moved for. The staircase's
own smallest rung is 0.1 ms, so no tool can show less.*

## T2: what does it do with a value below zero?

Two ways of moving the clock, as freeze 21 and D15-1 say. For tools that read the time through the
C library, `libfaketime` moves only the tool's own clock. For the four Go tools, which read the
time without it, the driver's own clock was stepped back and put back after each run, measured
against the hypervisor's PTP clock, which a step does not move (`scripts/clock_step.py`). The
offsets are the median reference trip plus 1 ms and plus 3 ms, and the shift actually reached at
the clock is what each run is judged at.

| tool | how the clock was moved | offset measured | freeze 21, as written | first printed | D23-1 as implemented |
|---|---|---|---|---|---|
| `valkey-benchmark` | libfaketime | 1.784 ms | **one clock** | one clock | undecided |
|  |  | 3.809 ms | **one clock** | one clock | undecided |
| `memtier_benchmark` | libfaketime | 1.819 ms | **one clock** | one clock | undecided |
|  |  | 3.811 ms | **one clock** | one clock | undecided |
| `kafka-producer-perf` | libfaketime | 3.261 ms | **one clock** | one clock | undecided |
|  |  | 5.232 ms | **one clock** | one clock | undecided |
| `kafka-end-to-end` | libfaketime | 3.398 ms | **undecided** (drops zero and below, one clock) | undecided | one clock |
|  |  | 5.423 ms | **one clock** | one clock | one clock |
| `rdkafka_performance` | libfaketime | 3.434 ms | **undecided** (all five stand) | undecided | undecided |
|  |  | 5.476 ms | **undecided** (keeps every value, negatives to zero) | undecided | undecided |
| `wrk2` | libfaketime | 1.834 ms | **undecided** (drops negatives, drops zero and below, one clock) | one clock | — |
|  |  | 3.819 ms | **one clock** | one clock | — |
| `rabbitmq-perftest` | libfaketime | 1.885 ms | **undecided** (drops negatives, drops zero and below, one clock) | undecided | — |
|  |  | 3.887 ms | **one clock** | one clock | — |
| `vegeta` | machine clock | 1.823 ms | **one clock** | one clock | — |
|  |  | 3.822 ms | **one clock** | one clock | — |
| `hey` | machine clock | 1.814 ms | **one clock** | one clock | — |
|  |  | 3.812 ms | **one clock** | one clock | — |
| `k6` | machine clock | 1.828 ms | **one clock** | one clock | — |
|  |  | 3.831 ms | **one clock** | one clock | — |
| `nats-latency` | machine clock | 1.752 ms | **one clock** | one clock | — |
|  |  | 3.754 ms | **one clock** | one clock | — |

**At the larger offset, ten tools are one clock and the eleventh is not.** At the smaller one,
three more are undecided. That is the rule working, not failing: at 1.8 ms a tool that drops its
negatives keeps only the few trips that were longer than the offset, and their average can land
close to where it started. `wrk2`'s average moved −0.100 ms. One clock predicts 0, dropping the
negatives +0.123 and dropping zero with them +0.141, and its noise allows 0.253, so all three
stand. At 3.8 ms nearly every trip is below zero and the three come apart.

**`rdkafka_performance` is the one tool whose figures moved.** At 5.48 ms its average changed
−5.42 ms and its minimum −5.08. One clock is ruled out. Keeping every value predicts −5.38, which
fits to 0.04 ms, but replacing the negatives with zero predicts −2.45, and a noise of 1.11 ms gives
an allowance of 4.72 that cannot exclude it. Freeze 21 said before this was judged that this tool
could not be decided at its offsets, and it is not.

**The column that changed.** "First printed" is what the program said when the run was judged.
One run differs from the rule as written: `wrk2` at 1.834 ms, printed as one clock. The program
held wrk2's count — all 3,001 requests it sent in 60 s — against the 5,000 trips of our
reference, which is another run of another client. So it read the tool as having dropped
values, and ruled out both dropping behaviours on "it counted 3001 where this would count 50".
Freeze 21 says a count short *of what was sent* is evidence, and wrk2 was asked to send 3,000.
Judged as written, that run is undecided. Nothing else moves: none of the other 21 runs was
decided by a count. The tool's answer, one clock, stands on its larger offset.

"D23-1 as implemented" is the verdict the same readings got before freeze 21, kept beside as that
freeze asks. It held every hypothesis to the tool's printing step, as small as 0.00001 ms, where
two runs of one tool minutes apart differ by 0.07 to 0.16 ms. So it called three tools undecided
that freeze 21 finds on one clock. One run went the other way: `kafka-end-to-end` at 3.40 ms was
one clock under D23-1, and freeze 21's allowance leaves dropping zero and below standing beside it.

*Glosses. **Offset measured**: how far the clock was found to have moved, not how far it was asked
to. **Undecided**: more than one explanation fits within the tool's own noise, so this run does
not say which, and the ones left are named. **Allowance**: how far a change may be from a
prediction and still fit, three times the tool's noise times √2, never under two printing steps.
**Control**: the same tool at no offset, run minutes before in the same session.*

## T3: does waiting in line show?

The figure T1's slope was read on, from one run in each cell. The last column is that figure's
own run-to-run noise, from the T1 staircase.

| tool | figure | idle | 88% load | idle, go-first | 88%, go-first | its own noise |
|---|---|---|---|---|---|---|
| `valkey-benchmark` | p50 | 0.447 | 0.527 | 0.551 | 0.543 | 0.049 |
| `memtier_benchmark` | p50 | 0.655 | 0.655 | 0.711 | 0.591 | 0.059 |
| `kafka-producer-perf` | p50 | 1.000 | 1.000 | 1.000 | 1.000 | 0.280 |
| `kafka-end-to-end` | p50 | 1.000 | 1.000 | 1.000 | 1.000 | 0.312 |
| `rdkafka_performance` | avg | 510.22 | 508.13 | 510.28 | 506.97 | 1.112 |
| `wrk2` | p50 | 1.390 | 1.470 | 1.260 | 1.190 | 0.060 |
| `rabbitmq-perftest` | p50 | 0.809 | 0.779 | 0.939 | 0.811 | 0.051 |
| `vegeta` | p50 | 0.742 | 0.768 | 0.749 | 0.811 | 0.037 |
| `hey` | p50 | 0.800 | 0.800 | 0.800 | 0.800 | 0.036 |
| `k6` | p50 | 0.712 | 0.716 | 0.733 | 0.732 | 0.008 |
| `nats-latency` | p50 | 0.638 | 0.634 | 0.624 | 0.608 | 0.049 |

The plan fixed no rule for T3, so nothing here is a verdict. As a yardstick only, the same
allowance T2 uses was set beside each difference: the load's effect (88% against idle), and
go-first's at each load. One of the 33 differences exceeds it: `wrk2`'s go-first at 88%, −0.280
ms against an allowance of 0.256. Apart from that one, at 50 requests a second on a machine whose
cores are 88% busy, no tool's figure shows time spent waiting for a CPU beyond what one run to
the next shows anyway. Where the load does show, it shows in the tail rather than the middle:
hey's median held at 0.8 ms in all four cells while its 99th percentile went from 1.8 ms idle to
3.2 at 88%, and its average from 0.8 to 1.0.

*Glosses. **88% load**: every core kept busy 88% of the time by a program that does nothing else.
**Go-first**: real-time priority on the tool's own process, so it runs ahead of everything else.*

## T4: what can each report?

| tool | figures read from its output | the trip it times, from how it is run |
|---|---|---|
| `valkey-benchmark` | avg, min, p50, p99, max | a Redis round trip, from the client |
| `memtier_benchmark` | avg, p50, p99 | a Redis round trip, from the client |
| `kafka-producer-perf` | avg, p50, p99, max | send to acknowledgement, at the producer |
| `kafka-end-to-end` | avg, p50, p99 | produce and consume, in one process |
| `rdkafka_performance` | avg, min, max | the producer stamps the payload, the consumer subtracts |
| `wrk2` | avg, p50, p99 | an HTTP round trip, from the client |
| `rabbitmq-perftest` | min, p50, p99, max | produce and consume, in one process |
| `vegeta` | avg, min, p50, p99, max | an HTTP round trip, from the client |
| `hey` | avg, min, p50, p99, max | an HTTP round trip, from the client |
| `k6` | avg, min, p50, p99, max | an HTTP round trip, from the client |
| `nats-latency` | min, p50, p99, max | publish and receive, in one process |

The figures are the ones our readers take from each tool's real output in its T4 run. That is
what T1 to T3 use, not every figure each tool prints: wrk2, for one, prints a whole spectrum of
percentiles. The trip is the plan's reading of each invocation, from the addendum of freeze 21,
and T2 is its test: every tool the addendum put on one clock was found on one, and the one it put
on two was found on two. Two of the eleven print no average, so T2 judges them on their minimum
alone.

*Glosses. **Round trip**: out and back, timed at one end by one clock. **One-way**: from one
program to another, which needs two clocks, and is what a streaming system is used for.*

## What went wrong on the way, and what was done

Four faults were found writing this up. They are recorded in the index's table of faults.

- **T2's count was compared against the wrong number.** It is described under T2 above. The judge
  now holds a count against what the tool was asked to send, which `tools_run.sh` writes beside
  every run. A short count now rules out only the behaviours that keep every value, because how
  many values a dropping tool keeps depends on its own trips, not ours. Every T2 reading was judged
  again, and exactly one verdict changes. With the program unchanged, the re-judgement first
  reproduced all 22 printed verdicts and every reason given, which shows it repeats the call
  exactly.
- **The Go tools' clock was never put back.** `tools.sh` read `step_clock` through `$(...)`, which
  runs it in a subshell, so the record of the step never reached `unstep_clock`. Each second offset
  landed on top of the first, 5.3 to 5.7 ms from the PTP clock where 3.8 was planned. The only sign
  was the job's last line: "the clock now: −4.978339 ms". Those twelve runs are kept, with the
  reason, in `tools_go_clock_not_restored_20260925`. After the fix (f6859319) the four tools were
  run again. Every step started within 0.025 ms of the PTP clock and was back within 0.047 ms, and
  T2 now checks that and refuses to go on otherwise. A test runs T2's own lines with stand-ins for
  the clock, and it fails on the old call.
- **T1's step finder reads only the average.** `rabbitmq-perftest` and `nats-latency` print none,
  so T1 found no step for them and T2 fell back to their printing step, 0.001 ms, "which is a
  bound". This decides nothing: judged again with a 0.1 ms step, all four of their runs keep their
  verdicts. It is left as it is, because changing it changes T2's inputs for the other nine, and
  that is for the next freeze.
- **hey's percentiles were never read.** Its documentation shows "50% in 0.0008 secs". What it
  prints is "50%% in", its own format string's escape left in, and the reader was written from the
  documentation and tested against a fixture that followed it. The reader now takes one percent
  sign or two, with a test built from hey's real output, which fails on the old reader. hey's
  runs were read again from their raw output, not run again. Its T2 verdicts, changes, allowances
  and noise come out identical, because T2 judges the average and the minimum. What changes is
  T1's slope, now taken on the median, and the figure T3 and T4 show.

**One departure from the plan.** It says the Go tools' T2 uses "a second machine with a
deliberately offset clock, restored afterwards". What was used is the driver itself, with nothing
else running on it. `machine_is_quiet` refuses to step the clock under a campaign, the step is
measured against a clock it does not move, and it is put back and checked after each run. The
reason for a second machine is to keep other work off the stepped clock. That is kept here by the
refusal, and the tools run where their T1 ran.

*Glosses. **Subshell**: a copy of the running script. A value set in it is lost when it ends.
**PTP clock**: the hypervisor's own clock, exposed to the machine and not moved when the system
clock is.*

## Where the numbers are

- Runs: `runs/azure/collected/matched/snapshot_20260925T002916Z/runs/azure/tools` (this page's
  tables are read from it), with the first copy, taken before the Go tools were run again, in
  `snapshot_20260925T001228Z`. Each carries SHA256SUMS.
- T2 judged again, as written: `runs/azure/collected/matched/t2_rejudged_20260925/`, one folder
  per run with its verdict, its page and the exact call.
- hey read again: `runs/azure/collected/matched/hey_reread_20260925/`, one reading per run.
- Logs of the last two jobs: `tools_logs_20260925` in the same snapshot.

## Pocket dictionary

| | |
|---|---|
| **allowance** | how far a change may sit from a prediction and still fit |
| **control** | the tool at no offset, minutes before, in the same session |
| **crossings** | how often the timed interval passes through the delayed direction |
| **go-first** | real-time priority on the tool's process |
| **libfaketime** | a library that makes one program read the time early or late |
| **noise** | how much a figure varies between runs with nothing changed |
| **one clock** | both timestamps a tool subtracts come from the same clock |
| **p50, p99** | the median, and the value 99% of results fall below |
| **PTP clock** | the hypervisor's clock, which stepping the system clock leaves alone |
| **reference** | our own client on the same path |
| **slope** | how far a figure moves per millisecond added |
| **step** | the smallest change a printout can show |
| **undecided** | more than one explanation fits within the tool's noise |
