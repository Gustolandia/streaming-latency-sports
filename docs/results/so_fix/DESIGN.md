# Freeze 40 (plan version 43): the full fix in the form a benchmark tool would use

Draft written 14 October 2026, before any pilot or judged run of its block. What prompted it: F1
(freeze 39, 13 October) showed that a latency timed between the kernel's own timestamps, as a
message leaves the client machine and as it returns, held still across background load and
priority, while the latency timed from the publish call rose 4.3 to 4.6-fold in its tail at normal
priority. F1 read the kernel's timestamps from packet captures. A benchmark tool would not run a
capture: it would ask the kernel for the same timestamps on its own sockets, through the
`SO_TIMESTAMPING` socket option. The paper says so and says it was not tested. This block tests it.

## The claim

The kernel timestamps a benchmark client reads on its own sockets through `SO_TIMESTAMPING`, the
transmit timestamp of the packet that carries each message out and the receive timestamp of the
packet that brings it back, give the same kernel-timed latency as the packet captures, message by
message, and so keep the clients' waits out of the latency as F1's captures did.

## What is measured, per message

All on the driver's one clock, as in F1:

- `t_pub`, `t_tx`, `t_rx`, `t_recv`: as F1 (the publish call; the captures' departure and arrival
  timestamps, `sender_full.pcap` and `receiver_full.pcap`; the consumer's own timestamp).
- `t_tx_so`: the kernel's software transmit timestamp of the producer's send call that carried the
  end of the message's event id, read by the producer from its socket's error queue
  (`SOF_TIMESTAMPING_TX_SOFTWARE | SOF_TIMESTAMPING_SOFTWARE | SOF_TIMESTAMPING_OPT_ID |
  SOF_TIMESTAMPING_OPT_TSONLY`). Each timestamp carries the byte offset of the last byte of its send
  call, so a message is matched to the first timestamp whose offset is at or after its id's last
  byte.
- `t_rx_so`: the kernel's software receive timestamp returned with the consumer's read that
  delivered the end of the message's event id (`SOF_TIMESTAMPING_RX_SOFTWARE`, the `SCM_TIMESTAMPING`
  control message of `recvmsg`). For a stream socket that is the timestamp of the last packet the
  read consumed.

From them: `W = t_rx - t_tx` (F1's kernel-timed latency, from the captures, the reference) and
`W_so = t_rx_so - t_tx_so`, the same latency as a tool reads it.

How the clients read them: a small module, `scripts/so_timestamps.py`, replaces the socket class in
the producer's and the consumer's process before the client library opens its connections. On each
connection to the broker's port it turns the option on at the first send or read, after the
connection is established, so that byte offsets count from the first byte sent. It drains the error
queue on every send and read and when the socket closes, and it finds each event id in the bytes it
sends and reads exactly as `scripts/full_fix.py` finds them in the captures. The client libraries
are unchanged. The captures run beside it, as F1 ran them, as the reference.

## Design

The first x86 pair (matched), as F1. Both brokers, the base slice at 3 ms, no added delay, 50
messages a second for 130 s with the 30 s warm-up left out. Two factors on the driver, as F1: no
background load or 88%; normal or real-time priority (SCHED_FIFO 80) for the producer and the
consumer together. Eight setups, six shuffled rounds, 48 runs, every run judged by
`scripts/run_integrity.py` as it ends, only passing runs read. Each run captures both directions,
as F1, and reads the socket timestamps. The network card's own timestamps are not captured.

## Predictions

A setup's value is the median over its passing runs of each run's statistic over its messages.

- **G-a (the socket option agrees with the captures).** In every setup, the median over its runs
  of each run's median of `|W_so - W|` is at most 20 µs, and the median over its runs of each run's
  99th percentile of `|W_so - W|` is at most 100 µs.
- **G-b (the median holds).** As F1's F-a for `W_so`: for each broker and each priority, its median
  at 88% load lies within 10% of its median idle; for each broker and each load, its median at
  real-time priority lies within 10% of its median at normal priority.
- **G-c (the tail holds).** The same comparisons for `W_so`'s 99th percentile, within 25%.
- **G-d (nothing below zero, nothing lost).** No message has `W_so` at or below zero, and the
  messages missing either socket timestamp are counted and are under 0.5% of each run's.
- **G-e (the effect is there, and is the clients').** As F1's F-d with `W_so`: at normal priority,
  `D`'s 99th percentile at 88% load is at least 1.5 times its value idle on both brokers, and
  `W_so`'s mean moves by less than a fifth of the rise in `D`'s mean.

## Why these margins

G-b to G-e repeat F1's, so the two blocks can be read side by side. G-a: the receive timestamps
should be identical, since the capture and the consumer's socket read the same timestamp the kernel
put on the packet, unless one read consumes more than one packet, which at 50 messages a second
should be rare. The transmit timestamps differ by the path from the capture's tap on eth0 to the
driver that hands the packet to the card, a few microseconds. 20 µs is about 3% of F1's kernel-timed
latency, wide enough for that path and narrow enough that an instrument that disagreed would show;
100 µs in the tail leaves room for the rare read that consumes two packets, and stays far below the
milliseconds the clients' waits add.

## What could go wrong, and what it would mean

- **No transmit timestamps.** A virtual network driver may not timestamp in software. If the pilot
  finds that the producer receives none, the producer asks for the transmit timestamp at the queue
  instead (`SOF_TIMESTAMPING_TX_SCHED`), as the instrument the pilot settles, and the plan says so.
- **A read that consumes several packets.** The consumer's receive timestamp is that of the last
  packet a read consumed, so a message read together with a later one is timed late. That would
  show in G-a's tail, and in G-c at normal priority under load.
- **The error queue.** While it holds a timestamp, the socket reports itself readable; a client
  that never drained it would spin. The module drains it on every send and read.
- **The module costs time.** It reads and scans every byte the clients send and read, in Python.
  That lengthens `H_out` and `H_in`, the clients' own time, and not `W_so`, which the kernel stamps.
  `D` and the clients' time are compared with F1's, described and not judged.

## Pilot (instruments only; predictions above do not change)

One round of the eight setups: both captures and both socket files write, every event id is
found in all four, `t_tx_so` and `t_rx_so` arrive for every message, and `W_so` and `W` are
compared for every message. Its runs are not judged.
