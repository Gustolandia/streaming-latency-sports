# T1, rdkafka_performance: half a second reported where the trip is 2.6 ms

24 September 2026, first x86 pair (`matched`). This is T1 for `rdkafka_performance` — what the
tool can report at all — run after the shakedown of [D23-2](rdkafka-shakedown.md) established
that its consumer reads what its producer sends. Its earlier staircase, of 22 September, measured
nothing and is reported as nothing rather than as zero.

*Glosses. **T1**: the staircase that adds a known delay to the path in ten steps and asks what
each tool then reports. **Reference**: our own client, on the same path, in the same minutes, so
the tool's number is read against a trip rather than against a hope. **Step**: the smallest change
a tool's own output can express.*

## What ran

| | |
|---|---|
| Tool | `rdkafka_performance`, librdkafka 2.15.1-3-g6f86c8 |
| Invocation | `-C -l -t sbl-tools -p 0 -o end` (consumer), `-P -l -s 512 -a 1 -r 50` (producer) |
| Steps | 0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.1, 1.5, 2.0 ms, in shuffled order |
| Readings | 3,000 per step, 30,000 in all |
| Reference | our own Kafka client, same path, 17:43 UTC |

## What it reported

| added delay | median reported | | added delay | median reported |
|---|---|---|---|---|
| 0 ms | 506.03 ms | | 0.7 ms | 504.51 ms |
| 0.1 ms | 503.20 ms | | 0.9 ms | 505.24 ms |
| 0.2 ms | 504.03 ms | | 1.1 ms | 507.40 ms |
| 0.3 ms | 523.24 ms | | 1.5 ms | 505.85 ms |
| 0.5 ms | 504.21 ms | | 2.0 ms | 507.06 ms |

At zero added delay the tool reports **510.7 ms** on average, from 16.5 to 1009.0. Our own client,
on the same path at the same time, measures a trip of **about 2.6 ms** — the reference run's
readings run 2.42 to 3.52 ms.

## The finding

**The tool reports a figure about two hundred times the trip, and cannot see two milliseconds.**
Across the whole staircase its median moves by about one millisecond — 506.03 at no delay,
507.06 at 2 ms — and that movement is invisible inside a spread from 16 to 1,009 ms. A reader of
its output would not learn that the path had changed at all.

And it says so to ten microseconds. The tool's own step — the smallest change its output can
express — is **0.01 ms**, recorded beside every reading. It is precise to a hundredth of a
millisecond while being half a second wrong, which is the failure this paper is about, found in a
benchmark rather than argued from a model.

That matters more here than it would for any of the other ten. This is the only tool of the
eleven whose subtraction spans two clocks — the producer stamps the payload and the consumer
subtracts — so it is the only one that measures a one-way latency at all, and the only one in
which the artifact this paper describes could appear. The instrument best placed to show the
effect is the one whose own resolution hides it.

## Why, and what is deliberately not done

Not the network, and not the clocks. It is the tool's own send-side batching: the example
program sets `queue.buffering.max.ms` to a second, so messages are stamped as they are enqueued
and delivered in one batch a second later. The shakedown's trials show it directly — with that
one property set to 5 ms and nothing else changed, the median falls to **7.34 ms**, spread 6.87
to 14.14.

The default is what is reported. Plan version 23 says the tools are run as their own
documentation runs them, and that a configuration a tool does not normally take is a second
reading beside the first and never in place of it. So 510.7 ms is the reading, 7.34 ms is the
second reading, and the gap between them is the result. Tuning the first into the second would
answer a question about our arrangement rather than about the tool, and what a reader of
librdkafka's own examples would get is the first.

## What this does not say

It does not say the tool is wrong. It reports, correctly, the age of a message when the consumer
sees it, and under its own defaults most of that age is time the producer held it. It says that
a figure so reported is not the network latency a streaming system cares about, and that nothing
in the tool's output — least of all its hundredth-of-a-millisecond step — tells a reader which
of the two they are looking at.

T2 is not yet asked of this tool. Its question, what a tool does with values below zero, now
needs the control run of D23-1, which is not written yet.
