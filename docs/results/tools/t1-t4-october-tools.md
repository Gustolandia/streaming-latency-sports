# T1–T4 and K1, the five tools read in October: four measure the path, three span two clocks

Two blocks, 11 October 2026. **Freeze 32** (plan version 35, `freezes/32-experiment-plan`, public
before any judged run) ran Xinfra Monitor, Strimzi Canary, Kafka's Trogdor and RabbitMQ Stream
PerfTest (as producer and consumer, two processes) on the first x86 pair (`matched`), four rounds
of T1 to T4 each, 304 runs, and K1, Kafka's end-to-end tool beside an observer, six rounds of four
cells. **Freeze 33** (plan version 36, `freezes/33-experiment-plan`) ran the Yahoo Streaming
Benchmark (YSB) on the second x86 pair (`matched-b`), of the same machine type and processor, four
rounds, 76 runs. Every run was read; none stopped and none was run again. The runs are home,
checked file by file against the fingerprints taken on the pairs, in
`runs/azure/collected/matched/v35_20261011T105302Z` (2,535 files) and
`runs/azure/collected/matched-b/v36_20261011T063738Z` (2,385 files); the pilots that preceded the
freezes are beside them. Both pairs stopped themselves when the runs were home.

*Glosses. **T1**, the staircase: a known delay added to the path in ten steps, 0 to 2 ms, asking
how far each tool's figure moves; the band fixed in advance is 0.5 to 1.5 ms per millisecond and
per crossing. **T2**, forced negatives: the clock of the tool's subtracting process is moved back
by more than its trip. **T3**: idle against 88% load, with and without go-first (the tool at
real-time priority). **T4**: what the tool can report at all. **K1**: how often a message is
readable before Kafka's end-to-end tool has its acknowledgment, which the tool, by its order of
calls, cannot see. **Two clocks**: the tool's two timestamps are taken by two processes, the
arrangement in which a value below zero can arise.*

## The short of it

- **Four of the five follow the delay.** Xinfra Monitor, Strimzi Canary, Trogdor and Stream
  PerfTest measured the path in all sixteen staircases. YSB did not, as freeze 33 predicted, but
  for a reason found after the runs: each write of its results waits for four replies from Redis
  that cross the delay, so its figure moved by up to 236 ms per millisecond added (below).
- **Xinfra Monitor and Strimzi Canary time against one clock, as their invocations were read**:
  each runs its producer and consumer in one process, and moving that process's clock left their
  figures within a quarter of the offset in all 16 of their offset runs.
- **Trogdor, Stream PerfTest and YSB span two clocks.** Stream PerfTest dropped what went below
  zero: it kept 628 to 1,226 of 3,000 latencies at the smaller offset and 3 to 4 at the larger.
  Trogdor replaces a negative with zero, so its figures fell by its own latency, about 2 ms, at
  both offsets: more than half the smaller offset (read two) and less than half the larger
  (undecided). YSB's notebook dropped what went below zero, and also drops 20 to 26% of windows
  with no clock moved.
- **K1: under load, 11 to 41% of the messages Kafka's end-to-end tool timed were readable before
  it had their acknowledgment**, against 0.5 to 4.4% idle and at most 0.2% with the tool at
  real-time priority. All three predictions held in all six rounds.
- **With these five, 14 of the 21 tools run time both ends in one process and 7 span two.**

## T1: the staircase

Slope of the figure the staircase was read on, per millisecond added, by round; one crossing each.

| Tool | Figure | Round 1 | Round 2 | Round 3 | Round 4 |
|---|---|---|---|---|---|
| xinfra-monitor | average | 1.039 | 1.012 | 1.035 | 1.060 |
| strimzi-canary | median | 1.000 | 1.000 | 1.000 | 1.000 |
| trogdor | median | 1.141 | 1.141 | 1.141 | 1.141 |
| stream-perftest | median | 1.141 | 1.141 | 1.141 | 1.028 |
| ysb | median | 235.516 | 85.137 | −0.238 | 190.916 |

The three whole-millisecond medians move in one-millisecond steps, which is why the same slope,
1.141, recurs: it is the least-squares slope of that step pattern over the ten delays. Xinfra
Monitor prints no median and is read on its average.

**YSB, read after its runs** (`scripts/ysb_post_hoc.py`, `ysb_flush.csv`). Its figure is the time
of a window's last write to Redis less the window's end. Once a second its processor writes every
campaign's window, one campaign after another, and each write of a window Redis already holds waits
for four replies (`hmget`, `hincrBy`, `hset`, `lpush`), each of which crossed the delay T1 adds.
Within a flush, the writes of one window for successive campaigns were 3 ms apart with no delay and
10 to 11 ms apart with 2 ms added; the gap grew by 3.1 to 3.7 ms per millisecond added in each
round, close to the four replies. The gap was read in the 27 of the 40 staircase runs whose
collected file holds the same windows for every campaign. Round 3's slope of −0.24 comes from its
scattered medians, not from a smaller effect: one run there (0.3 ms) wrote two windows some three
seconds late, and without it the round's slope is 31.

## T2: forced negatives

Freeze 21's verdict, then version 34's answer from the offset alone (D34-2), for each offset run.

| Tool | Offsets (ms) | Freeze 21 | Version 34, clocks | What it kept |
|---|---|---|---|---|
| xinfra-monitor | 2.67–2.81, 4.68–4.82 | 7 of 8 "times against one clock", 1 undecided | one, 8 of 8 | every value |
| strimzi-canary | 2.69–2.74, 4.69–4.74 | 7 of 8 "times against one clock", 1 undecided | one, 8 of 8 | every value |
| trogdor | 2.71–2.78, 4.69–4.80 | undecided, 8 of 8 | two at the smaller offset, undecided at the larger | every value, negatives as zero |
| stream-perftest | 1.83–1.99, 3.90–3.99 | undecided, 8 of 8 | two, 8 of 8 | 628–1,226 and 3–4 of 3,000 |
| ysb | 326–424 | 5 of 8 "times against one clock", 3 undecided | two, 8 of 8 | 578–749 of 1,200–1,300 windows |

**Trogdor** records `Long.max(0L, ...)`: a value below zero becomes the histogram's floor. Every
latency goes below zero under either offset, so its median fell by its own latency, 2 ms, in all
eight runs (average by 2.05 to 2.17 ms). That is more than half the smaller offset and between a
quarter and a half of the larger, which D34-2 leaves undecided.

**YSB.** Both judges take their base from a reference that drops nothing, and YSB's notebook drops
every window whose last write came before the window's end: 20 to 26% of windows in the four
controls. Freeze 21's judge read five of its eight runs as timing against one clock: its allowance
for a change is three times the scatter of the figure across the T1 staircase (times √2), and the
flush had spread YSB's figure there by hundreds of milliseconds, so the allowance (194 to 838 ms)
exceeded the change (190 to 244 ms) in those five. Version 34's judge left all eight undecided.
Read directly against YSB's own reference instead (`ysb_t2_fit.csv`), "drops the negatives" fits
every run: it predicts 49 to 50% of windows kept, against 46 to 58% kept, and averages within 38 ms
of those printed, while every run's average fell by 179 ms or more from its round's control, where
one clock predicts no fall. This reading was made after the runs; the verdicts stand as given.

## T3: idle against 88% load

Median over the rounds, in milliseconds (`tools_load_table.tex`).

| Tool | Median idle | Median 88% | 99th idle | 99th 88% | 99th 88%, real-time |
|---|---|---|---|---|---|
| Trogdor | 2.00 | 3.00 | 3.00 | 8.00 | 6.00 |
| Stream PerfTest | 1.00 | 1.00 | 2.00 | 5.00 | 4.00 |
| Strimzi Canary | 1.00 | 1.00 | 1.00 | 3.00 | 1.00 |
| Xinfra Monitor | — | — | 2.00 | 5.00 | 2.00 |

Every tail rose under the load. Trogdor's median moved by one step of the whole milliseconds it
prints, the only median of the eighteen tools that moved by more than 0.2 ms. Real-time priority
took the whole rise back for the two one-process tools, and a third and two fifths of it for Stream
PerfTest and Trogdor, whose producers, in another process, did not run at real-time priority. YSB is left out: its figure is set by its flush, not by the trip a waiting thread lengthens.

## T4: what each can report

All five report whole milliseconds. Xinfra Monitor reports an average, a maximum and percentiles
estimated from its metrics library's buckets (its 99th percentile reads 1.9992 ms), and no median.
Strimzi Canary logs each duration and keeps a Prometheus histogram whose lowest bucket is 5 ms.
Trogdor's histogram has 1 ms steps. Stream PerfTest prints its latency percentiles once a second
and, with `--prometheus`, a count and a sum of the latencies it recorded. YSB writes each window's
last update less the window's start.

## K1: Kafka's end-to-end tool beside an observer

A copy of the tool changed only to trace each message (`external/kafka_e2e`), beside an observer
at real-time priority on the same machine and clock; 3,000 messages per cell, six rounds
(`k1.csv`, `k1_verdicts.json`, judged by `scripts/kafka_clamp.py`).

| Load | Kafka's tool | Readable first, median | range | S, median (ms) | tool's 99th (ms) | observer's 99th (ms) |
|---|---|---|---|---|---|---|
| idle | normal priority | 0.9% | 0.5–4.4% | 0.19 | 3 | 1.99 |
| idle | real-time priority | 0.1% | 0.1–0.2% | 0.20 | 3 | 2.02 |
| 88% | normal priority | 19.9% | 10.7–41.3% | 0.21 | 10 | 4.60 |
| 88% | real-time priority | 0.1% | 0.0–0.2% | 0.22 | 3 | 2.11 |

K1-a, the instrument (every message's traced time covers its own wait for the acknowledgment),
held in all 24 runs. K1-b (such messages occur under the load), K1-c (the load raises their share)
and K1-d (real-time priority takes it back) each held in all six rounds, a one-sided sign test of
1 in 64. Under the load the tool timed each such message a median 2.6 ms after the observer could
read it, and its own 99th percentile was 10 ms where the observer's was 4.6 ms.
