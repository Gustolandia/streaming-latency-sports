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
were corrected (commit b1be30b3):

- K-d judged every setup that had quintiles; the design names each broker's setup at 88% load and
  normal priority. The others are now described.
- R-a, K-e, L-c and block I's decision pooled messages across a setup's runs; the design's rule is
  the median over a setup's runs of each run's value, unless a prediction says it pools (K-a and K-b
  do). They now take the median over runs.

No margin and no prediction changed.

*Words in this part.* **Judge**: the program, written before the runs, that turns a block's runs
into verdicts. **Pooled**: counted over all of a setup's messages at once, rather than run by run.

## The result

Every judged run passed the integrity rule at its first attempt but one: block K's
`r006-K-kafka-l0-rt-a1` (Kafka, idle, real-time priority) failed it because its consumer received
no message, and the campaign ran it again as `a2`, as the plan provides.

### The second pair: blocks P, L and I (read 15 October, after the pair's hold at 18:52 UTC)

| Prediction | Required | The runs gave | Verdict |
|---|---|---|---|
| P-a | W_so rises 0.9 to 1.1 ms per ms added | Kafka 0.93, Redis 0.95 | confirmed |
| P-b | A's median moves at most 10% between any two delays | Kafka 18%, Redis 22% | not confirmed |
| P-c | D rises 0.9 to 1.1 ms per ms added | Kafka 0.94, Redis 0.95 | confirmed |
| L-a | \|W_so - W\| at most 20 µs at every rung, every setup | 1.2 to 3.0 µs | confirmed |
| L-b | at 50 messages a second, W_so within 10% under 88% load | Kafka -6.3%, Redis +25.7% | not confirmed |
| L-c | at 50 messages a second, at most 1% of messages flagged | 0% in every setup | confirmed |
| I | idle=poll halves Redis's share of S in [-250, -150) µs | 4.2% to 5.7% | the mode is not an idle processor's wake |

**Read after the verdicts.**
- *P-b.* A did not follow the delay. Its setup medians were 1,416, 1,498 and 1,272 µs on Kafka at
  0, 1 and 2 ms, and 721, 878 and 864 µs on Redis; within one setup its runs spread by up to 40%
  (Kafka at 2 ms: 1,244 to 1,744 µs). With four runs a setup, the 10% band was narrower than A's
  run-to-run spread. The kernel-timed latency carried the added delay one for one (P-a) whatever A
  did.
- *L-b.* On Redis the kernel-timed latency rose from 465 to 584 µs under load, in the captures
  (462 to 581 µs) as in the sockets, so the rise is in the kernel's timestamps, not in the module.
  The mean of D rose 591 µs and the mean of W_so 121 µs: about a fifth of the load's effect on the
  mean end-to-end latency entered W_so there, while D's 99th percentile rose 5.3-fold (858 to
  4,521 µs) and W_so's 1.27-fold. On Kafka W_so fell 56 µs while D's mean rose 1,337 µs. The
  pull flag was zero in every run at this rate and no Redis read drained more than one packet, so
  neither of the two cases the paper names is the cause. Freezes 39 and 40 found W still under load
  on the first pair; what lengthened Redis's on the second pair is not traced. D's statistics and
  the means were added to the ladder's run table after the verdicts, to describe this; no judge
  reads them, and `l_verdicts.json` came out the same, byte for byte, when the table was read again.
- *The ladder, described.* At 2,000 messages a second, 99.7% (Kafka) and 96.2% (Redis) of messages
  were delivered in answer to a request sent after the message left, and their W_so was longer:
  1,213 against 767 µs on Kafka, 953 against 551 µs on Redis. At 500 messages a second the flag
  stayed at 0.2% and 0.07%. Kafka's reads drained more than one packet in 97% of reads at 50 and
  75% at 2,000; Redis's almost never. The share of S below zero, idle, was 0.56% and 0.04% at 50
  (Kafka, Redis), 0.4% and 18% at 500, and 3.7% and 0.7% at 2,000. At 500 it split between runs:
  two of the eight (one per broker) had 88.5% and 99.6% of S below zero, with A above D by a steady
  margin for the whole run; the rest stayed at 0.1 to 20%. The ladder's journal covered the
  consumer only, so these runs cannot say which arrived first.
- *Block I, described.* The acknowledging thread's median delay was 191 µs (default boot) and 176
  µs (idle=poll) on Kafka, 63 and 62 µs on Redis; on Kafka every acknowledgment was read more than
  100 µs after it arrived, on either boot.

### The first pair: blocks K and R (read 15 October, after the pair's hold at 19:48 UTC)

| Prediction | Required | The runs gave | Verdict |
|---|---|---|---|
| K-v | the journal's acknowledgment arrival within 20 µs of the capture's | 0.0 µs in every setup; every acknowledgment found | confirmed |
| K-a | Kafka: at least 90% of S < 0 with S_k >= 0 | 99.75% at 88% load (4,024 values), 91.7% at real-time priority (60) | confirmed |
| K-b | Redis, real-time, sixteen workers: at least half of S < 0 with S_k < 0 | 100% idle (5,160 values), 99.8% at 88% (4,098) | confirmed |
| K-c | 99th percentile of d_ack: at least 1.5x under load, at most half at real-time | Kafka 229, 3,887, 274 µs; Redis 106, 3,167, 94 µs (idle, 88% normal, 88% real-time) | confirmed |
| K-d | at 88%, normal priority: Pr[S < 0 \| S_k] falls across quintiles and lies within 2x of Pr[d_ack - d_recv > S_k] | within 1.14x (Kafka) and 1.85x (Redis) in every quintile; does not fall | not confirmed |
| K-e | one send worker against sixteen, Redis real-time | idle: 0.04% against 1.44% (the lock sets it); 88%: 0.06% against 0.04% (it does not) | decision recorded |
| R-a | rate of S < 0 with NO_RUN_TO_PARITY at most 2/3 of the rate with it | Kafka 13.5% against 13.2%; Redis 5.6% against 6.1% | not confirmed |
| R-b | 99th percentile of d_ack with NO_RUN_TO_PARITY at most 2/3 | Kafka 3,885 against 3,906 µs; Redis 3,165 against 3,166 µs | not confirmed |

**The decision K-b names.** DESIGN.md's rule attributes to reply order exactly the share of each
broker's values of S below zero that have S_k < 0, and to late reading the rest. On Kafka that
share is 0.25% at 88% load and 8.3% at real-time priority (and 5 to 23% of the 13 and 19 values in
the idle setups, too few to judge): Kafka's values below zero are late readings. On Redis it is 95.1
to 100% in every setup with sixteen workers, at either priority and either load: Redis's values
below zero are, by this rule, its reply order.

**Read after the verdicts.**
- *Kafka's margin.* The acknowledgment reached the client machine first in almost every message:
  the setup medians of S_k were 72 to 92 µs, and S_k < 0 held for under 1% of messages in all but
  two runs (13% and 32%). The acknowledging thread's median delay was 163 to 180 µs in every
  setup, the client's own processing, and its tail was the wait: 3.9 ms at 88% load, back to
  0.27 ms at real-time priority.
- *Redis's order, run by run.* In 16 of the 24 sixteen-worker runs the delivery came first for most
  messages (setup medians of S_k of -16 to -51 µs where it did); in the rest the acknowledgment
  came first. With the delivery first, S < 0 needs no wait, only that the acknowledging thread's
  delay not fall short of the consumer's by more than the delivery's lead
  (S = S_k + d_recv - d_ack). Whether a Redis run's S fell below zero then depended on the two
  delays: most runs stayed under 6%, and a few ran at 82 to 88% for the whole run, as two of the
  ladder's runs at 500 messages a second did.
- *K-d.* The prediction from each setup's own delays was nearly flat across the quintiles
  (Kafka 13.5% to 13.3%), because the margins (57 to 159 µs) are short beside the waits; the
  observed shares (11.7% to 15.0%) rose and then fell within that band. The paper's p G(S_k), with
  p the share of acknowledgments read more than 0.1 ms after they arrived, predicted 99.6% to 100%
  on Kafka, where every acknowledgment is read later than that: the client's processing alone
  exceeds 0.1 ms there.
- *R.* With run-to-parity off, the rate and the acknowledging thread's 99th-percentile delay stayed
  where they were on both brokers, run for run (Kafka's runs 11% to 26% either way, its delay tails
  3.8 to 4.6 ms either way).
- *K-e.* The sixteen-worker Redis rates are medians over runs whose values below zero sit mostly in
  one or two runs; the decision is the design's, stated as it falls at each load.

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
campaign. Each pair's own work list runs the first two lines. Block R is read like K, without
quintiles; the second pair's blocks are read with its own addresses, the ladder's three rungs
together and with their 20 s warm-up, and block I's two boots together:

```bash
python scripts/order_scope.py read --block R --runs runs/azure/collected/matched/r/runs --driver 10.1.1.10 --broker 10.1.1.21 --receiver 10.1.1.11 --out docs/results/order_scope/r_runs.csv
python scripts/order_scope.py read --block P --runs runs/azure/collected/matched-b/p/runs --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 --out docs/results/order_scope/p_runs.csv
python scripts/order_scope.py read --block L --runs runs/azure/collected/matched-b/l50/runs --runs runs/azure/collected/matched-b/l500/runs --runs runs/azure/collected/matched-b/l2000/runs --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 --warmup 20 --out docs/results/order_scope/l_runs.csv
python scripts/order_scope.py read --block I --runs runs/azure/collected/matched-b/i_default/runs --runs runs/azure/collected/matched-b/i_poll/runs --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 --out docs/results/order_scope/i_runs.csv
```

Each is judged as K is, with `judge --block` and its own table.

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
