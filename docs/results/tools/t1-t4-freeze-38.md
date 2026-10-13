# Google's Pub/Sub load test through T1 to T4 and S1: freeze 38

Freeze 38 (plan version 41, `freezes/38-experiment-plan`, public as `98738766` before any judged
run) ran the last tool of the second October reading, Google's Cloud Pub/Sub load test framework,
at commit cd7d07bb with the client library its pom pins (google-cloud-pubsub 1.69.0), built by
Maven 3.9.9 on Java 8 and run on Java 11. It ran from the second x86 pair's driver (`matched-b`)
against Google's own Pub/Sub, four rounds, on 13 October 2026 between 00:10 and 04:48 UTC. Jobs
173 to 193 all finished with status 0; none stopped on a rule, and none was run again. The runs are
home, checked file by file against fingerprints taken on the pair, in
`runs/azure/collected/matched-b/v41_20261013T044951Z` (425 files), and the four pilots beside them
in `pilots_v41_20261013T044957Z` (266 files). Neither copy holds any part of the service account's
key, only the path it was read from. Once the runs were home the key, the service account and the
Google Cloud project made for the runs were deleted, and the pair stopped itself.

*Glosses. **Bucket**: the tool puts each latency v into bucket floor(log1.5 v), floored at 0, so
bucket n holds the values from 1.5^n to 1.5^(n+1) ms and bucket 0 every value at or below 1 ms, a
zero and a value below zero included. **Printed range**: its controller prints a percentile as
[1.5^(n-1), 1.5^n), one bucket below the values in it. **T1**: a known delay added toward the
driver in steps. **T2**: the clock of the process that subtracts moved back by more than the tool's
trip. **T3**: idle against 88% load, with and without real-time priority. **T4**: what the tool
reports with its clock a second ahead. **S1**: the driver's wall clock stepped back about five times
a second while the tool runs. **Running duration**: how long a client says it has run, timed on
its wall clock from a start given on that clock.*

## The short of it

*In plain words: under a moved clock its controller crashes, blaming negative values, and prints
nothing for the subscriber; a second ahead, it prints less than a second; one prediction failed in
one round, because Pub/Sub itself got faster between two runs.*

- **T2-l held in all four rounds.** Under offsets of 26.6 to 89.5 ms, bucket 0 held 87 to 120 of
  the 120 values its subscriber counted in each run, and its controller threw "Programming error:
  negative values appear in buckets." once, printed no figure for the subscriber, wrote no
  `output.csv`, and ran on until stopped at six minutes (exit 124). Each control printed its figures
  and exited with status 0.
- **T4-l held in all four rounds.** With the subscriber's clock a second ahead, every round printed
  its median as [656.84, 985.26) ms, below a second, while every value but one lay in bucket 17,
  from 985.3 to 1,477.9 ms.
- **S1-l failed, in round 2 only.** That round's stepped run printed its median as
  [11.39, 17.09) ms and its control [25.63, 38.44): two buckets apart, where S1-l allowed one. The
  steps put 17 of its 80 counted values in bucket 0, but without them its median stays in the same
  bucket. Pub/Sub delivered faster in the stepped run than in its control five minutes before.
- **Its clocks are not answered, as predicted.** Both judges left every offset run undecided:
  there was no figure to hold against the control.
- **39 of its 48 runs needed a second attempt.** The first never began, because its controller's
  first call to Pub/Sub's REST API timed out, as in the first pilot. No run needed a third.

## T1 and the reference

*In plain words: a managed service is out of the staircase's reach, so the tool was its own
reference, and its trip was read off what it printed.*

Its traffic goes to a managed service the staircase cannot reach, so T1 was its zero step alone,
as PerfKit's was, and it was its own reference, run once more at no offset (D41-3). Its controller
prints a range one bucket below the values in it, so the trip T2 took its offsets from is 1.5 times
the top of the median's printed range.

| Round | Zero step's median (ms) | Reference's median (ms) | Trip (ms) | Offsets asked (ms) |
|---|---|---|---|---|
| 1 | [11.39, 17.09) | [11.39, 17.09) | 25.63 | 26.63, 28.63 |
| 2 | [38.44, 57.67) | [38.44, 57.67) | 86.50 | 87.50, 89.50 |
| 3 | [11.39, 17.09) | [11.39, 17.09) | 25.63 | 26.63, 28.63 |
| 4 | [17.09, 25.63) | [11.39, 17.09) | 25.63 | 26.63, 28.63 |

Round 4's zero step and reference, minutes apart, printed medians a bucket apart, as Pub/Sub's own
delivery moved.

## T2, the moved clock

*In plain words: once at least half the subscriber's values sat at or below a millisecond, its
controller crashed every time, as predicted.*

| Round | Offsets measured (ms) | Bucket 0, of 120 | Thrown | output.csv | Exit |
|---|---|---|---|---|---|
| 1 | 26.67, 28.63 | 96, 110 | 1, 1 | no, no | 124, 124 |
| 2 | 87.47, 89.45 | 120, 120 | 1, 1 | no, no | 124, 124 |
| 3 | 26.65, 28.65 | 103, 110 | 1, 1 | no, no | 124, 124 |
| 4 | 26.65, 28.63 | 87, 109 | 1, 1 | no, no | 124, 124 |

The counts are those its driver logged from each check response, summed as its controller sums
them (`docs/results/tools/pubsub_runs.csv`). Its controller's percentile search, run again on them,
throws exactly where bucket 0 holds at least half, which it did in every offset run. Each control
printed its subscriber's median, in rounds 1, 3 and 4 as [11.39, 17.09) ms and in round 2 as
[38.44, 57.67) ms, wrote its `output.csv` and exited with status 0. Version 34's rule answered every
offset run undecided, "no average, median or minimum to hold against its control", and freeze 21's
judge did the same, "it ran to the end but printed no latency under the offset". The latter's own
line, "0 of 1 trips go below zero", passes the reference's trip less the offset, -1.04 ms in round 1,
through the step the reader gives the tool, 12.8 ms, the width of the widest range its zero step
printed, where it reads zero; it decided nothing.

## T4, a second ahead

*In plain words: every value went up by a second, and it printed a range wholly below a second.*

With its subscriber's clock a second ahead under libfaketime, every value rose by 1,000 ms. In
every round its controller printed the subscriber's median as [656.84, 985.26) ms, and bucket 17,
from 985.3 to 1,477.9 ms, held every value but one, which lay in bucket 18 in round 2. Its JVM's
`Math.pow(1.5, 16)` gives 656.8408355712891 where 1.5^16 is 656.8408203125, so the printed lower
bound differs from the true one in the eighth figure.

## T3, the busy machine

*In plain words: its figures are buckets as wide as a third of themselves, from a managed service,
so a wait for a core cannot be read in them.*

Its printed medians moved among buckets 6 to 10, [7.59, 11.39) to [38.44, 57.67) ms, from cell to
cell and round to round, idle and loaded alike: round 2's idle cells sat at bucket 9 and round 4's
at 7. The range it printed for its idle 99th percentile, the median over the four rounds, was some
13 ms wide, and the bucket above it, where the values lie, some 19 ms: either is wider than the most
any tool's 99th percentile rose under the load (7.0 ms), so the supplement describes it apart, as it
does PerfKit Benchmarker. In round 3 its loaded cell without real-time priority printed its 99th percentile as
[7,481.8, 11,222.7) ms, the bucket below six of its 120 values, which took 11.2 to 16.8 s. Why was
not read.

## S1, the stepped clock

*In plain words: nothing it printed said a value had gone below zero; three rounds held, and the
one that failed did so because Pub/Sub's own speed changed between the two runs.*

| Round | Control's median | Stepped median | Buckets apart | Steps | Clock after (ms) |
|---|---|---|---|---|---|
| 1 | [38.44, 57.67) | [38.44, 57.67) | 0 | 1,737 | -0.003 |
| 2 | [25.63, 38.44) | [11.39, 17.09) | 2 | 1,735 | -0.045 |
| 3 | [11.39, 17.09) | [11.39, 17.09) | 0 | 1,720 | -0.022 |
| 4 | [17.09, 25.63) | [11.39, 17.09) | 1 | 1,719 | -0.027 |

Each step was 50 ms back, 85.95 to 86.85 s in all per run. No line any stepped run printed
mentioned a value below zero. In round 2 the stepped run's 80 counted values lay in buckets 0 (17),
6 (15), 7 (37), 8 (7) and 9 (4), and its control's 120 in buckets 7 (28), 8 (24), 9 (67) and
10 (1). Its controller's search gives bucket 7 for the stepped run with or without the 17, and
bucket 9 for its control: the steps did not move the median, Pub/Sub's own delivery did, between a
control and a stepped run five minutes apart. The one bucket S1-l allowed was narrower than that
drift. In the same run's burn-in, which its controller does not count, the steps put a whole burst
of 40 in bucket 0.

## What its stepped runs counted

*In plain words: under the steps its clients' clocks ran slow, so the minute it ignores at the start
lasted longer, and it counted two bursts instead of three.*

Its publisher sends one message a second as bursts of 40 every 40 s, and its controller counts a
check response only where the running duration it reports is past the minute's burn-in
(`Client.java:246-250`). The client times that duration on its wall clock from a start given on
the same clock, and under the steps that clock ran about a quarter slow. So each stepped run's
clients reported their first burst with a running duration below zero, -6.8 to -7.7 s, and its
controller counted two of the five bursts, 80 values, where every control counted three, 120. Each
count is the one its controller printed.

## The attempts set aside

*In plain words: most runs had to be started twice, because a first call to Google timed out; the
plan said what to do, and it was done.*

In 39 of its 48 runs, the four references included, the first attempt never began: its
controller's first call to Pub/Sub's REST API timed out ("Read timed out"), then a
`NullPointerException`. Each such attempt measured nothing, was set aside beside its run and made
again a minute later, as version 41 provides; each second attempt ran. The nine runs whose first
attempt began were the block's first run and, in every round, the two that followed a run stopped
at its six-minute limit. Each retry found the topic its failed attempt had made ("already exists,
reusing"). Every measured attempt's lines at ERROR level are the framework's own notices, "Creating
subscription" and "Shutting down server since JVM is shutting down".

## A fault in the reader, found after the runs

*In plain words: the program that summed its counts misfiled one response per stepped run; it is
corrected, and no verdict used those sums.*

The reader that ran on the pair read a check response's running duration as whole seconds above
zero, so a duration below zero, as each stepped run's first burst carried, was taken for one past
the burn-in. Its sums of the stepped runs' counts therefore held the first burst too. Corrected to
the controller's own rule, seconds and nanoseconds together, below zero allowed and a missing
duration taken as zero, every run's counted values sum to the count its controller printed: 80 in
each stepped run, and 120 in each of the other 36 runs that printed one. No verdict reads
those sums: T2-l, T4-l and S1-l read the printed ranges, the exception, the results file and the
exit status. The readings written on the pair are kept as written, and `scripts/pubsub_post_hoc.py`
reads every run again with the corrected reader.

## The pilots

Four pilots on 12 October, kept beside the judged runs, tested the instruments; version 41's D41-6
gives what each found. In short: an attempt that never started is made again; its runs leave the
receiver's namespace, which cannot resolve Google's names; under libfaketime Java 8's sleep never
returns, so the tool runs on Java 11; and an attempt whose controller gave up on a client is made
again. The first pilot's zero step was printed before the runner gave the burn-in's length, and the
post-hoc reading refuses it: read without its burn-in, the counts place its median a bucket above
the one it printed.

## Files

`docs/results/tools/v41.csv` and `v41_verdicts.json` (T2-l and T4-l, `scripts/block_v41.py`);
`s1_v41.csv` and `s1_v41_verdicts.json` (S1-l, `scripts/s1_block.py`); the rows of `tools_t1.csv`,
`tools_t2.csv` and `tools_t3.csv` for `pubsub-loadtest` (`scripts/tools_block.py`); and
`pubsub_runs.csv` (`scripts/pubsub_post_hoc.py`).

## Pocket dictionary

- **Managed service**: a broker run by a cloud provider, reached over the internet, whose machines
  we cannot touch.
- **Burn-in**: the first minute of a run, whose values the tool does not count.
- **Check response**: what each client sends its controller every few seconds: its running
  duration and the counts in each bucket since the last.
- **Exit 124**: the status `timeout` gives a program it stops at its limit.
- **Set aside**: an attempt that measured nothing, kept beside its run and not counted, as the plan
  provides.
