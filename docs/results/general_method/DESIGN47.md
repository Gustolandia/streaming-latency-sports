# Freeze 44 (plan version 47): the general method, tested

Written 23 October 2026, after freeze 43's block U was judged (`a1a94091`) and read again after its
verdicts (`docs/results/under_load/README.md`, "Read again after the verdicts"), and before any run
this version covers. Freezes 01 to 43 stay as they were fixed. This version adds new blocks; it
changes no earlier prediction.

**What prompted it.** Block U showed the mechanism. Under load, the consumer's thread is slow to ask
again for messages; a message that reaches the broker while no request waits there sits until the
next request comes, and the thread's delay enters even the kernel-timed latency. It did not show a
remedy, and it used block U's own clients only. Read after the verdicts, the same runs showed that
a client can tell which of its messages found no request waiting from its own timestamps, and that
it can tell best from one timestamp per packet. This version tests a general method built on that,
in the form the author set (23 October 2026):

1. **Kernel timestamps on the client machine, for every packet.** From the sockets where the
   language allows; otherwise from a packet capture on the client host, with no change to the
   client. Messages are matched by the broker's own ids: Kafka's offsets, Redis's entry ids, NATS
   JetStream's stream sequence; AMQP's message-id property where a classic queue gives no id both
   ends see.
2. **A check any tool can run from those timestamps:** was a request waiting at the broker when
   each message arrived? Messages that found none carry the client's own delay, and the tool
   reports that share beside the latency.
3. **Three latencies, each named:** what the broker and network deliver to a ready receiver (`F`);
   what reaches this client's kernel (`W`); what reaches the application (`D`).
4. **A remedy that depends on the protocol.** Redis, NATS and brokers that push with credit can keep
   requests waiting, which takes the thread out. Kafka can only shorten the gap with a fetch thread
   that does nothing else; its round trip is real latency.

The draft of this version was read, before this version, against the brokers' and the clients'
own source code; where this version differs from the draft, that reading is why (rows 5-11
below).

*Words in this part.*
- **Request waiting:** a request for messages, or a credit to deliver one, already at the broker
  when a message arrives there.
- **Depth:** how many requests a consumer keeps outstanding at the broker.
- **Credit:** RabbitMQ's prefetch count: deliveries the broker may send before the consumer
  acknowledges them.
- **Poisson sends:** sends whose gaps are drawn at random, independently, at the mean rate.
- **TOST:** two one-sided tests, which can show a ratio lies within a margin of 1, where a single
  test can only fail to show it moved.

## What the reading after block U's verdicts found, and what this version does with it

| | Found (post hoc, block U) | Version 47 |
|---|---|---|
| 1 | The check's certain reading, a delivering request that left more than 50 µs after the producer had its acknowledgment, made no false call in 3.02 million messages. | Kept as the check's lower bound, M2-a. |
| 2 | The estimate, with the two network crossings between the acknowledgment and the request added back, agreed with the broker's record on 96.9-99.2% of messages on Kafka at 2,000 a second from the client host's per-packet captures, and on only 86.6-98.2% from the sockets' per-read timestamps: under load the producer read several acknowledgments at once. | The check is read first from the client host's captures (point 1's "for every packet"). |
| 3 | Taking the crossings' floor from every request for messages failed at low rates, where every request waits: the allowance came out at 1-14 ms. | The floor counts only requests that cannot have waited, those that ask for no messages and those whose answer carried a message stored before they left, at least 100 of each least value. |
| 4 | Many messages sat within a few microseconds of their request at 2,000 a second; these carry almost none of the client's time. | The check reads to a resolution of 50 µs. |
| 5 | Block U's sends were evenly spaced (`--arrival constant`). | Every block sends Poisson, and every prediction that compares has its own baseline within this version; no margin is taken from block U where its arrivals would change it. |
| 6 | The socket's and the capture's receive timestamps are the same kernel value, so their 1-3 µs agreement tests the matching, not the clock. Per packet, block U's kernel receive timestamp trailed the card's own hardware timestamp by 18-20 µs at the 99th percentile on Redis and on idle Kafka, 82-99 µs on loaded Kafka (fetch answers arriving as bursts of packets), and was never earlier. | M1-a rests on the card, the independent clock. |
| 7 | At 2,000 a second, 64 waiting requests cover 32 ms; block U held one consumer for 997 ms. | Redis and NATS keep 256 requests waiting (NATS's `max_waiting` 1,024). |
| 8 | NATS's file store syncs every two minutes and gathers flushes; Kafka here writes to the page cache and Redis runs without persistence. | NATS JetStream runs with memory storage. |
| 9 | The broker images were floating tags (`redis:7`), and no run recorded the broker's version. | Every image is pinned by digest where it can be, and every run records each broker's image digest and server version. |
| 10 | λg/(λg + e^(−λg)) assumes Poisson arrivals at the broker, a constant gap and no broker handling; librdkafka sends its next fetch after parsing the answer. | Kafka's round trip is judged on the split of the gap (KC-h); the formula and the share of time with no fetch at the broker are described. |
| 11 | An idle SMT sibling removes the sibling's sharing of a core but not shared cache or interrupts; irqbalance was active on the testbed. | The whole-core test (C) runs with irqbalance off, the receiver's interrupts on the isolated vCPU, receive packet steering off, every other kit process off both vCPUs, and its own baseline and sibling-loaded arms. |
| 12 | Built against block U's runs before this version: where the remedy works no request on the consumer's connection can be shown not to have waited, so the estimate has no floor there, and the check could say only what it cannot rule out. | A second causal reading, of waiting, in counting form, its one bound checked in every run; the NATS and RabbitMQ consumers probe their own connections, which also gives the estimate its floor there. |

## What is measured

All on the client host's one clock, except where a line names the broker's or the card's.

- **`W`:** a message's arrival at the consumer's kernel less its departure from the producer's, from
  the client host's captures, each message named by the broker's id (`scripts/client_wire.py`): the
  capture time of the packet carrying its record's last byte as it left, and the time the last byte
  of its record in the delivery could first be read. For the Python clients the sockets' `W_so` is
  described beside it.
- **`D`:** the consumer application's time of the message less the producer application's time of
  its send, from the clients' own files, joined to the wire by the broker's id.
- **The check.** For each message, the delivering request (for push with credit, the acknowledgment
  that freed its credit, `amqp_frames.released()`; for NATS, the oldest pull request still outstanding, as the server serves them first in, first out):
  - **The broker's record:** from the broker's own capture, matched by the broker's id, the request
    reached the broker more than 50 µs after the message's acknowledgment left it (none), before the
    message arrived (waiting), or in between (close).
  - **The certain reading:** the request left the consumer more than 50 µs after the producer had
    the acknowledgment.
  - **The estimate:** the same with the pair of connections' two crossings, `C_hat`, added back:
    the least acknowledgment round trip on the producer's connection, plus the least round trip on
    the consumer's connection of a request that cannot have waited, less the least `W` over the pair,
    less an allowance per broker set from the pilot's broker captures; each least value from at
    least 100 values, or no estimate. A probe's reply cannot have waited: the NATS consumer sends
    `PING` on its receive connection every 100 ms, and the RabbitMQ consumer a synchronous method on
    a second channel of its connection.
  - **The certain reading of waiting:** m certainly found a request waiting where, on its delivering
    connection, the requests for messages that had left by `B` before m left, less the answers to
    them that had arrived by `B` after m's acknowledgment arrived, number at least one. A request is
    timed by its last byte out and an answer by its first byte in; a status counts as an answer, a
    probe's reply does not. For push with credit, a credit was certainly free where the deliveries
    received by `B` after the acknowledgment arrived, less those acknowledged by acknowledgments sent
    by `B` before m left, are fewer than the prefetch. `B` = 10 ms, a bound on every one-way delay of
    the delivering connection, checked in every run: no retransmission or zero window on it in the
    client captures; its largest probe round trip below `B` (on Redis, where nothing overtakes a
    blocked read, the acknowledgment connection's round trips stand in, and the results say so); the
    largest per-packet `Q` below half of `B`, since a late receive timestamp could make an answer
    seem later than it was; and no silence in the captures longer than `B` while the measured messages
    are sent, from the warm-up's end to the plan's last send. `B` = 2 ms is described beside it.
- **`F`, as ready as the protocol allows:** where requests or credit can wait (Redis, NATS,
  RabbitMQ), `E3 = W − S`, `S` the time the message sat stored at the broker before its request came;
  on Kafka, `E2 = W − min(T_c, S)`, the latency had the client asked again at once, its round trip
  kept. Each from the broker's capture, and from the clients' timestamps alone with the estimate.
- **The turnaround `T_c`,** as version 46 defines it, from the client host's capture: the delivering
  request's departure less the arrival of the answer to the previous request for messages on its
  connection, less that connection's other requests' round trips in between.
- **By the load's state.** Each run's load is on and off in 5-s blocks; a message is in the state its
  send fell in, and one sent within 1 s after a switch is left out. Per state, the tail mean of a
  quantity is its mean over that state's messages above the state's 99th percentile of `W`. A run's
  on/off ratio is the on-state tail mean over the off-state's.
- **Per packet, against the card:** `Q`, the kernel's receive timestamp on the client host's capture
  less the card's hardware timestamp of the same packet, on the system's clock.
- **Kafka's gap at the broker:** from a fetch answer's departure to the next fetch's arrival, from
  the broker's capture; split into the client's part (its turnaround, on the client host's capture)
  and the rest (two crossings and the broker).

## The blocks

On the second x86 pair (blocks V, N, P, K, C, S) and the Arm pair (block A). Every run: 2,000
messages a second with Poisson sends, 70 s with a 20-s warm-up; the load at 70% switched on and off
in 5-s blocks, at a duty frozen per setup from the pilot; the producer at real-time priority, the
clients' collectors off where the client has one; every capture block U took (both client captures,
the card's, the broker's); the run's facts; each campaign primed on its broker. The integrity rule of
version 46 holds, with its lateness rule, and with each new client's settings.

| Block | Broker | Setups (consumer) | Runs |
|---|---|---|---|
| V | Redis 7.4.11 | waiting consumer at depth 1 (each replacement sent before the reply is read); at depth 256 with one reply per read; at depth 256 with the library's own reads | 12 |
| N | NATS 2.15.1, JetStream, memory storage | our pull consumer at depth 1; at depth 256 with one reply per read; nats.go's `Consume()` with its own defaults | 12 |
| P | RabbitMQ 4.3.7 | prefetch 1; prefetch 1,000 | 8 |
| K | Kafka 4.1.1 | kafka-python 2.3.2, Java kafka-clients 3.9.0 (classic), franz-go 1.19.5 and librdkafka 2.15.1, each at normal priority; librdkafka with only its broker thread (`rdk:broker1`) at real-time priority | 20 |
| C | Kafka 4.1.1 | kafka-python at real-time priority, with irqbalance off and the receiver's interrupts on one vCPU, receive packet steering off: not isolated (baseline); the consumer alone on that vCPU's core, its sibling idle; the same, its sibling loaded | 12 |
| S | Redis 7.4.11 | depth 256, the producer at normal priority; depth 256 under a loopback UDP load pinned to the receiver queue's vCPU, in the same blocks (described only) | 8 |
| A | Redis, Kafka (Arm pair) | V at depth 1 and 256; librdkafka at normal priority and with its broker thread at real-time priority | 16 |

Four rounds of each setup, in random order within each round, from seed 20261104
(`docs/results/general_method/*_design.json`): 72 runs on the x86 pair and 16 on the Arm pair. The
rounds stand until the pilot's power says otherwise (below).

## Predictions

A cell is one setup, or one comparison of two setups, in one block. A prediction holds where every
cell it reaches holds; a cell missing a value it needs is out of reach, reported and not judged. A
setup's value is the median over its passing runs, except where a line says a mean.

### The timestamps and the ids (point 1), every block

- **M1-a:** in every run with the card captured, `Q`'s 99th percentile is at most 150 µs, and no `Q`
  is below minus the card's clock window.
- **M1-b:** matching by the broker's ids pairs every message that matching by the payload's event id
  pairs, and pairs none differently.
- **M1-c (V and N at depth 256):** with one reply per read, the sockets' `W_so` is within 10 µs of the
  capture's `W` at the 99th percentile; with the library's own reads, under load, it exceeds it by at
  least 100 µs there.

### The check (point 2), every block

- **M2-a:** in no run does the certain reading call a message unwaited that the broker's record shows
  waiting or close. Cause and effect alone give it, so a failure means a clock or a timestamp is wrong.
- **M2-b:** in every run where the estimate has a value, its share of messages that found none is
  within 6 points of the broker's (block U's largest, read after its verdicts, was 5.83).
- **M2-c (the remedy's own check; V and N at depth 256, nats.go, P at 1,000):** the broker's record
  shows a request or credit waiting for at least 99.9% of messages, and the certain reading of
  waiting certifies at least 99.9% of them. In a run whose check of `B` fails, the second clause is
  out of reach. The estimate's share is reported where it has a value.

### The three latencies (point 3)

- **M3-a:** where M2-c holds, over the messages the broker's record shows found a request or credit
  waiting, `W`'s tail is held still: its on/off ratio lies within 1/1.2 and 1.2 by TOST across the
  setup's runs at α = 0.05; while `D`'s on/off ratio is at least 1.5. The same over all messages is
  described.
- **M3-b:** at depth 1 (V, N), at prefetch 1 (P), and for each in-poll Kafka client at normal
  priority (K), `W`'s tail on/off ratio is at least 1.5. Where it is, removing the client's part of
  the request gap takes out at least half of its rise:
  - that part is the turnaround, or for P the credit turnaround: from a delivery's arrival to the
    departure of the acknowledgment that frees the next credit;
  - "removing" means `E2 = W − min(turnaround, S)`;
  - the share is `1 − (E2_on − E2_off)/(W_on − W_off)` of tail means, a setup's value the mean over
    its runs, with a run-level 95% interval from 2,000 draws, seed 20261104.

### The remedy by protocol (point 4)

- **V-a, N-a, P-a:** M3-a, on Redis at depth 256, on NATS at depth 256 and with nats.go, and on
  RabbitMQ at prefetch 1,000.
- **KC-a:** each in-poll Kafka client (kafka-python, Java, franz-go) at normal priority: its
  turnaround's tail mean is at least 1.5 times higher in the on-blocks.
- **KC-b:** where `W`'s tail on/off ratio is at least 1.5, removing the turnaround takes out at least
  half of the rise, as M3-b reads it.
- **KC-c:** librdkafka's rise of the turnaround's tail mean is at most half of each in-poll client's.
- **KC-d:** with only librdkafka's broker thread at real-time priority, `W`'s tail is held still as
  M3-a reads it, over all messages, while `D`'s on/off ratio is at least 1.5.
- **KC-h (the round trip is real latency):** in the same setup, the turnaround's tail on/off ratio is
  at most 1.2, and in both load states at least half of the messages found no fetch waiting, by the
  broker's record. Described beside it: the share of time no fetch waited at the broker, from the
  broker's capture, and λg/(λg + e^(−λg)) with g the run's median gap there.
- **C-a:** in block C, the residual (`W`'s on-block tail mean less its off-block one, within runs)
  with the consumer alone on its core and the sibling idle is at most a third of the baseline arm's.
  The sibling-loaded arm is described between them.

### Replication and scope

- **A:** V-a, M2-c (Redis) and KC-d hold on the Arm pair.
- **S, described only:** how M1-a, M2-a, M2-c and M3-a fare with the producer at normal priority, and
  under a load heavy in network softirq work, with the receive path's squeeze counters and
  ksoftirqd's time.

## Pilot, round a (instruments only; the predictions above do not change)

After this version is public and before any judged run: one run of each x86 setup and each Arm
setup, each campaign primed, the loaded setups with the second duty correction so that each finds
its duty. It checks, and the record states before any judged run:
- the integrity rule and the lateness rule hold, every message is found in the broker's and the
  card's captures by its id with no packet dropped, and the new clients' files read as the old;
- each broker's image digest and version as pinned; nats-server's archive layout; the Go and Java
  consumers built on the driver, and their thread names in `/proc`;
- Redis serves a queued request in the same pass (a request waiting for every message at depth 256),
  NATS keeps 256 requests waiting, RabbitMQ keeps a credit waiting at 1,000;
- the whole-core arms' masks, interrupt placement and irqbalance's state as set;
- each loaded setup's frozen duty; the check's allowance per broker from the pilot's broker
  captures; and the rounds, simulated from the pilot by the rule of version 45, each clause whose
  pilot effect does not clear its margin resting on the floor of four with its power stated.

If a client cannot run as designed, its setup is left out and the record says why, before any judged
run; no margin changes.

## What could go wrong, and what it would mean

- **A request still not waiting at depth 256** (M2-c fails): the remedy is not as simple as the
  protocol allows, and V-a, N-a or P-a stay unjudged where M2-c fails.
- **`W` moving with requests waiting** (M3-a fails while M2-c holds): something other than the
  request gap carries load into the kernel-timed latency: the receive path's own processing, which
  block S probes, or the producer's side.
- **librdkafka's broker thread not holding** (KC-d fails): the dedicated thread shares locks with the
  application's thread, and that is the remedy's limit on Kafka.
- **The estimate missing the broker's share** (M2-b fails): the check stays a lower bound, and the
  paper reports only the certain reading as a tool's check.
