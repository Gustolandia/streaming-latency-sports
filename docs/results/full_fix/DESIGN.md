# Freeze 39 (plan version 42): a full fix, tested

Draft written 13 October 2026, before any pilot. What prompted it: R1's packet captures, read
after the fact on 13 October (exploratory, `r1_kernel_vs_app.csv`), show that a latency timed to
the kernel's receive time no longer moves with the consumer's priority or the machine's load.
That reading covers the receiving side only, because R1 captured only the receiver's packets.
This block tests the whole fix, both sides, under predictions fixed here first.

## The claim

A benchmark that takes both of a message's timestamps where the message physically leaves and
enters the client machine, in the kernel, never in a program thread, reports the latency of the
system under test (network and broker) with nothing added by the host's threads: no late reading,
no value at or below zero, nothing to delete, and no wait for a core. The host's own waits are
measured beside it, so the latency an application sees is that plus them.

## What is measured, per message

All four times on the driver's one clock (CLOCK_REALTIME; the kernel's capture timestamps and
the clients' `time.time_ns()` share it, as R1's zero negative kernel delays show).

- `t_pub`: the producer's clock at the publish call (`t_prod_send_ns`, as in every campaign run).
- `t_tx`: the kernel's capture time of the packet carrying the end of the message's event id in
  the reassembled driver-to-broker byte stream (new: a capture in the root namespace on eth0,
  nanosecond timestamps, `dst host BROKER and dst port` the broker's port).
- `t_rx`: the same in the broker-to-receiver stream, in the receiver's namespace (R1's capture,
  unchanged).
- `t_recv`: the consumer's clock when it stamps the message (`t_consume_ns`).

From them:
- `D = t_recv - t_pub`, what a benchmark timed from the publish call reports (the paper's repair);
- `W = t_rx - t_tx`, the wire time: network and broker, the fix;
- `H_send = t_tx - t_pub` and `H_recv = t_recv - t_rx`, the host's two waits, so `D = H_send + W +
  H_recv` for every message by arithmetic.

## Design

The first x86 pair (matched), as R1. Both brokers. The base slice at 3 ms, no added delay, 50
messages a second for 130 s with the 30 s warm-up left out, as R1. Two factors on the driver:
background load, idle (0%) or 88%; and priority, normal or real-time (SCHED_FIFO 80) for both
processes that read the clock, producer and consumer. Eight setups (broker x load x priority), six
shuffled rounds, 48 runs, every run judged by scripts/run_integrity.py as it ends, only passing
runs read. Each run captures both directions. Pauses are marked as R1 marked them and reported
beside every comparison.

## Predictions

A setup's value is the median over its passing runs of each run's statistic over its messages.

- **F-a (the median holds).** For each broker and each priority, W's median at 88% load lies within
  10% of its median idle; and for each broker and each load, W's median at real-time priority lies
  within 10% of its median at normal priority.
- **F-b (the tail holds).** The same comparisons for W's 99th percentile, within 25%.
- **F-c (nothing below zero, nothing lost).** No message has W at or below zero. Every message the
  consumer stamped is found in both captures, or the unmatched are counted and are under 0.5% of a
  run's messages.
- **F-d (the effect is there, and is the host's).** In the same runs, at normal priority, D's 99th
  percentile at 88% load is at least 1.5 times its value idle on both brokers (the effect the fix
  must remove, present in the runs that test it). And the rise in D's mean from idle to 88% load at
  normal priority is carried by H_send + H_recv: W's mean changes by less than a fifth of that rise.

Kafka-specific, the hypothesis behind the Kafka tail in R1's D_k: its client's background thread
sends a message after the publish call returns, so under load H_send carries a wait for a core.
- **F-e (Kafka's send-side wait).** On Kafka at 88% load and normal priority, H_send's mean is at
  least 0.2 ms larger than idle; on Redis, whose client writes from the calling thread, H_send's
  mean moves by less than 0.1 ms.

## Why these margins

From R1's exploratory reading (13 Oct): within a setup, run medians of the kernel-timed latency
spread over about 110 us on Redis (650 to 763) and 330 us on Kafka (1,318 to 1,645), so with six
runs a setup's median is known to about 20 and 60 us. Ten percent of the medians is about 70 and
140 us: wider than that uncertainty, and narrower than the host effect the fix must remove at the
median, about 170 us on Redis and 400 to 1,000 us on Kafka. In the tail the effect is several
milliseconds (Redis D p99 4.5 ms at normal priority against 1.0 ms at real-time), so 25% of a
sub-millisecond W p99 separates the two easily.

## What could go wrong, and what it would mean

- **Idle can be slower.** An idle virtual CPU halts, and waking it for a network interrupt takes
  the hypervisor some microseconds. The kernel's software timestamp is taken after that, so W could
  be slightly longer idle than under load. If F-a fails that way, the fix is full for the host's
  threads but not for its interrupt path, and the NIC's own timestamps would be needed. The pilot
  checks whether the driver's network card offers them (`ethtool -T`); if it does, receive-side
  hardware timestamps are captured beside the software ones and reported, not judged.
- **Softirq deferral.** Under heavy interrupt load the kernel can defer receive processing to a
  normal-priority thread. At 50 messages a second it should not; if W's tail rises under load, this
  is the first suspect.
- **A pause.** A disk-write stall holds a run's messages and releases them together; where it holds
  them before `t_tx`, W excludes it, and where in the broker, W includes it, as it should.
- **Matching.** Kafka batches; a produce request can carry several messages. Each message's `t_tx`
  is the packet carrying the end of its own event id, so batching does not move it.

## Pilot (instruments only; predictions above do not change)

One round of the eight setups: both captures write, every event id is found in both, `t_tx` <
`t_rx` for every message, and `ethtool -T` on eth0 and the accelerated-networking interface.
