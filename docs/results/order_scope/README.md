# Freeze 41: the acknowledgment's own arrival, and where the kernel-timed latency holds

Two referees of the paper's ninth version asked, independently, for the same measurements: the
acknowledgment's own arrival, timed by the kernel, to settle the one rival the paper left open; a
positive control and a rate ladder for the kernel-timed latency of freezes 39 and 40; and direct
checks of the timescale. Freeze 41 runs them. Its plan is frozen in
[`freezes/41-experiment-plan`](../../../freezes/41-experiment-plan/) (plan version 44), and its
predictions were written, and fingerprinted, before any of its runs, the pilot included
([`DESIGN.md`](DESIGN.md), [`DESIGN.sha256`](DESIGN.sha256), commit 176ddbe7).

*Words in this part.* **Acknowledgment**: the broker's reply that it has the message.
**Kernel-timed**: timed from the timestamps the kernel takes as packets leave and arrive, which no
program thread's wait for a core can delay.

## What is measured

Each message carries, on the driver's one clock, the client's three readings (`t_pub`, `t_ack`,
`t_recv`), the captures' kernel timestamps (`t_tx`, `t_rx`), the sockets' (`t_tx_so`, `t_rx_so`),
and, new in this freeze, two read from a journal of every read and write the clients make on their
broker connections (`scripts/so_timestamps.py --so-journal`):

| Time | What it is |
|---|---|
| `t_rx_ack` | the kernel's receive timestamp of the producer's read that delivered the last byte of the message's acknowledgment |
| `t_req` | the kernel's transmit timestamp of the consumer's request that the message was delivered in answer to |

`scripts/so_journal.py` matches each acknowledgment and request to its message by the broker's own
wire format: Kafka's correlation ids, Redis's replies in request order. From them:

- the kernel-timed order `S_k = t_rx_so - t_rx_ack`, positive when the delivery reached the client
  machine after the acknowledgment, and holding no client thread's wait;
- the acknowledging thread's delay `d_ack = t_ack - t_rx_ack`, the late reading itself;
- the consumer's delay `d_recv = t_recv - t_rx_so`;
- the pull flag, set when the request a message was delivered in answer to left the client after
  the message itself did.

On one clock `S = S_k + d_recv - d_ack` for every message.

*Words in this part.* **Journal**: a copy of every byte a connection carries, with the kernel's
timestamp of each read. **Pull consumer**: a consumer that asks the broker for each batch.

## The blocks and their predictions

| Block | Pair | Runs | Predictions |
|---|---|---|---|
| K, the acknowledgment's arrival | first x86 (matched) | 60 | K-v the journal agrees with the capture; K-a on Kafka a value of S below zero is a late reading; K-b on Redis at real-time priority at least half are reply order; K-c the acknowledging thread's delay rises under load and falls at real-time priority; K-d the rate law, message by message; K-e a decision on CPython's interpreter lock |
| R, run-to-parity | first x86 | 24 | R-a and R-b: with the scheduler's RUN_TO_PARITY feature off, the rate of S below zero and the 99th percentile of `d_ack` fall to at most two-thirds |
| P, positive control | second x86 (matched-b) | 24 | P-a and P-c: the kernel-timed latency and D rise one for one with a delay added on the broker's path to the consumer; P-b the publish latency does not |
| L, rate ladder | second x86 | 32 | L-a sockets agree with captures at every rung; L-b at 50 messages a second the kernel-timed latency holds under 88% load; L-c at 50 messages a second at most 1% of messages carry the pull flag; at 500 and 2,000 the flag, multi-packet reads and S are described |
| I, idle processors | second x86 | 16 | a decision: whether `idle=poll` halves Redis's share of values of S between -250 and -150 µs |

## The pilot

On 15 October, after the predictions and before any judged run, and instruments only (row D44-10
of the plan). The first pair ran one round of K's and R's fourteen setups: every run passed the
integrity rule at its first attempt, every acknowledgment and request was found in the journals, and
each acknowledgment's receive timestamp in the journal was the capture's own. The second pair ran the
rate ladder idle at 50, 500 and 5,000 messages a second, then at 2,000, and at 500 and 2,000 under
88% load, and one run on the `idle=poll` boot. Three changes followed:

1. **The load check reads the background load.** At 500 messages a second Kafka's idle run failed
   the integrity rule three times, at 7.1 to 7.4% against 0%: the clients' own processor time had
   been counted as background load. The sampler now writes the clients' share of the machine beside
   its utilisation, and the load check subtracts it (`scripts/util_sampler.py`,
   `scripts/run_integrity.py`).
2. **The ladder's top rung is 2,000, and its upper rungs run idle.** At 5,000 messages a second
   Redis's producer sent 3,536 and 3,579 a second, so the top rung is 2,000, as the design provides.
   An 88% load could not be held beside the clients at 500 (83.5 to 85.7%) or 2,000 (80.0 to 81.9%),
   so those rungs run their idle setups only and L-b is judged at 50 messages a second.
3. **The reader takes each broker's port from the journal.** The kit's Kafka listens on 19092, and
   the reader had assumed 9092.

## Judge corrections made before any judged run was read

On 15 October, while blocks K and P were running and before any of their runs had been copied home
or read, a dry run of the judge on the pilot's runs found two departures from `DESIGN.md`, and both
were corrected (commit recorded below):

- K-d judged every setup that had quintiles; the design names each broker's setup at 88% load and
  normal priority. The others are now described.
- R-a, K-e, L-c and block I's decision pooled messages across a setup's runs; the design's rule is
  the median over a setup's runs of each run's value, unless a prediction says it pools (K-a and K-b
  do). They now take the median over runs.

No margin and no prediction changed.

*Words in this part.* **Judge**: the program, written before the runs, that turns a block's runs
into verdicts. **Pooled**: counted over all of a setup's messages at once, rather than run by run.

## The result

Not yet read: the judged runs began on 15 October at 15:47 UTC (block K) and 15:48 UTC (block P).

## How to reproduce

```bash
python3 scripts/run_queue.py make --design docs/results/order_scope/k_design.json --out runs/azure/queues/k.csv
bash cloud/azure/campaign.sh runs/azure/queues/k.csv
python scripts/collect_runs.py --hosts cloud/hosts.env --queue runs/azure/queues/k.csv
python scripts/order_scope.py read --block K --runs runs/azure/collected/matched/k/runs --driver 10.1.1.10 --broker 10.1.1.21 --receiver 10.1.1.11 --out docs/results/order_scope/k_runs.csv --quintiles docs/results/order_scope/k_bins.csv
python scripts/order_scope.py judge --block K --table docs/results/order_scope/k_runs.csv --quintiles docs/results/order_scope/k_bins.csv --out docs/results/order_scope/k_verdicts.json
```

The other blocks run the same way from their own design files (`r`, `p`, `l50`, `l500`, `l2000`,
`i_default`, `i_poll`); the rate ladder's rungs add `RATE=... DURATION=70 WARMUP_S=20` before the
campaign. Each pair's own work list runs the first two lines.

## Pocket dictionary

| Word | Plain meaning |
|---|---|
| Acknowledgment | the broker's reply to the producer that it has the message |
| Kernel-timed order, `S_k` | how long after the acknowledgment the delivery reached the client machine, by the kernel's own timestamps |
| Late reading | a clock read delayed while the reading thread waited for a core |
| Pull flag | set on a message delivered in answer to a request that left after the message did |
| RUN_TO_PARITY | the Linux scheduler rule that lets a running thread keep its core until its slice is spent |
| `idle=poll` | a boot option that makes an idle processor spin instead of halting |
| Setup | one combination of broker, load, priority and the block's own variable |
