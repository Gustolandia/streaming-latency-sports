# Freeze 42 (plan version 45): the consumer's turnaround, where load and rate bite together

Draft written 22 October 2026, before any pilot or judged run of its block. What prompted it: a
pull consumer lets its own thread's time back into the kernel-timed latency `W_so` through the
next request it sends, and a tool can time that time on its own socket (the post hoc checks
below). Freeze 41 judged `W_so` under load at 50 messages a second only, because an 88% load could
not be held beside the clients at 500 and 2,000 (D44-10). This block tests the fix and the
turnaround at 500 and 2,000 messages a second under the highest load the clients leave room for,
and finds where what remains lies.

**What we had read before this design, and what it informed.**
- Block L's judged runs (freeze 41), as the paper reports them.
- On 20 and 21 October, after block L's verdicts, the turnaround and two corrections on block L's
  idle runs at 500 and 2,000 messages a second, their acknowledgments rebuilt from the producer's
  capture. At 2,000 the turnaround's median was 0.42-0.51 ms on Kafka and 0.15-0.17 ms on Redis.
  Removing it brought `W_so`'s 99th percentile from 1.79 to 1.30-1.35 ms on Kafka and from 1.69 to
  1.32-1.34 ms on Redis (medians over runs; each range runs from the lower bound's median to the
  upper bound's). Every range in this section is rounded outward, so it holds every value read.
- On 22 October, freeze 41's pilot runs under load, never judged, seven of whose eight runs failed
  the load check:
  - at 2,000 a second with 88% asked, 80.0-82.0% held (one run per broker, two attempts each);
  - at 500 with 88% asked, 83.5-85.8% held.

  Under that load the turnaround's 99th percentile was 3.53-5.33 ms, against 0.20-0.81 ms idle
  (block L's idle runs and the pilot's). `W_so`'s 99th percentile was 2.5-4.1 times its idle value
  at 2,000, against the pilot's own idle runs, and 4.9-5.9 times at 500, against block L's idle
  medians. Removing the turnaround took out 68-101% of that rise, against the same references:
  88-101% on Kafka, 68-82% on Redis.

  These turnarounds were counted as an earlier script counted them, over every command on the
  consumer's connection and over the whole run. The registered reader counts only the requests for
  messages sent while the measured messages were in flight, which moves the values under load by
  about 1% and the idle ones by up to about 40 µs.

These readings set U-c's margins, the 80% load and the rounds. U-a's, U-b's and U-d's margins
repeat K-c's. No other prediction uses them.

## What is measured

All on the driver's one clock, as in freezes 39 to 41, except where a line names the broker's or
the card's.

- **From freeze 41, unchanged:**
  - `t_tx_so` and `t_rx_so`, so `W_so = t_rx_so − t_tx_so`;
  - `t_rx_ack`, from the producer's journal;
  - `t_req` and the pull flag, from the consumer's journal;
  - both client captures.
- **New, from the consumer's journal** (`scripts/under_load.py`), for each request for messages
  k on a connection (Kafka's fetch; Redis's XREAD or XREADGROUP):
  - `t_req(k)`, the transmit timestamp of its last byte;
  - `t_ans(k)`, the receive timestamp of the read that delivered its answer's last byte;
  - `t_before(k)`, the receive timestamp of the answer to the request just before it on that
    connection, whatever that request asked. On Redis the consumer's acknowledgment batches
    (XACK) go on the same connection, and a fetch after one waits from its answer;
  - **the turnaround** `T_c(k) = t_req(k) − t_before(k)`. This is the consumer's own time from an
    answer to its next request for messages: its thread's work and any wait for a core. No broker
    time and no network crossing are in it. A request sent before that answer came in counts as
    zero. A run's turnarounds are those of the requests sent while its measured messages were in
    flight, from the first one's publish to the last one's arrival.
- **New, per message: the thread's saving.** This is how much earlier the message would have
  arrived had its request left the moment the previous answer was in, with the network and the
  broker taking as long as they did. It lies between two bounds:
  - `s_min = min(T_c, max(0, t_req − t_rx_ack))`: the message was surely stored before its
    acknowledgment left the broker;
  - `s_max = min(T_c, max(0, t_req − t_tx_so))`: it was not stored before it left the client,
    taking the request's trip to the broker as no longer than the message's.

  Both bounds equal `T_c` when `t_rx_ack ≤ t_before`. **The thread-free latency** is
  `F = W_so − s_min`, which removes only what the thread surely added; `F_lo = W_so − s_max` is
  described beside it. `W_so` and `F` are read over the messages the journals time, those with
  every client-side time above, and the reader reports how many of a run's messages that is.
- **New, from a capture on the broker machine** (`broker_full.pcap`: both directions of the
  broker's port, kernel timestamps on the broker's clock). Per message:
  - `P_in`, the arrival of the last byte of the produce request that carried it, when the broker
    could first act on it;
  - `A_out`, the departure of the last byte of its acknowledgment;
  - `F_in`, the arrival of the last byte of the request it was delivered in answer to;
  - `R_out`, the departure of the byte that ends the message's own id in the answer that
    delivered it. Kafka carries an id twice in one record, in its key and its value; the later
    carrying is the one the consumer's socket and the card time, and `R_out` times it too.

  An id carried again in a later answer is a retry or a redelivery, and the carrying that reached
  the broker first is kept. Only differences of two of these are used, so the two machines'
  clocks never meet:
  - **the broker's residence** `R = R_out − P_in`;
  - **the broker-side saving range**, `[min(T_c, max(0, F_in − A_out)), min(T_c, max(0, F_in − P_in))]`.
    Its width is at most the broker's own handling of the produce request, `A_out − P_in`.
- **From the network card** (freeze 39's instrument, on this pair for the first time): the card's
  receive timestamp of the packet that carried the end of the message's id. **The consumer's
  receive processing** is `Q = t_rx_so − t_card`. It includes the wait of any packet that a later
  read drained with others, which is the consumer's side too. `Q` is the one term read across two
  clocks: the card's time is put on the system's through samples of the card's clock taken twice
  a second, and each run records how tightly the samples bracket it.
- **The split.** On one identity, `F = (W_so − R − Q) + (R − s_min) + Q`. Its three terms are:
  - the two network crossings and the producer's sending path below its timestamp;
  - the broker's residence less the thread's saving;
  - the consumer kernel's receive processing.

  `W_so` is a duration on the driver's clock and `R` one on the broker's. Where no run of the
  block has card timestamps, `Q` folds into the first term: every run's split carries it as zero,
  and the rows say so. Otherwise a run without them, its card capture or its clock samples having
  failed, has no split, stays out of U-e's and U-f's pool, and is listed.

## Block U

One block, on the second x86 pair, where block L and its pilots ran. The base slice is 3 ms and
the broker has no added delay.
- **Load:** none, or stress-ng on the driver.
- **Priority:** normal, or real-time (SCHED_FIFO 80) for the producer and the consumer together.
- **Every run takes:**
  - socket timestamps at the device queue;
  - both clients' journals;
  - the receiver's capture and both directions of the sender's;
  - the card's receive capture;
  - the broker's capture.

  Every capture takes a 32 MiB buffer, because a packet dropped from a capture leaves every later
  byte of its stream unread.
- **Judging:** every run is judged by `scripts/run_integrity.py` as it ends, and only passing runs
  are read.

| Rate | Setups on each broker | Runs (Kafka and Redis, 4 rounds) |
|---|---|---|
| 2,000 msg/s, 70 s (20 s warm-up) | idle; 80% load, normal priority; 80% load, real-time | 24 |
| 500 msg/s, 70 s (20 s warm-up) | idle; 80% load, normal priority; 80% load, real-time | 24 |
| 50 msg/s, 70 s (20 s warm-up) | idle; 88% load, normal priority | 16 |

That makes 64 runs in three campaigns, one per rate, with each round's setups in random order
(`u2000_design.json`, `u500_design.json`, `u50_design.json`; the pilot's are `up2000`, `up500`
and `up50`). `scripts/under_load.py` reads the runs into `u_runs.csv` and each setup's pooled
split into `u_tails.csv`, and judges them into `u_verdicts.json`.
- **Why 80%:** it is the least load freeze 41's pilot held beside the clients at 2,000 a second,
  80.0-82.0% when 88% was asked, so a load asked at 80% should hold within the integrity rule's
  3 points at both upper rates. Block U adds the producer's journal and the card's capture on the
  driver, so its pilot checks that.
- **Why 88% at 50:** it repeats L-b, whose Redis rise U-f traces.
- **Why four rounds:** simulated from block L's and freeze 41's pilots' per-run values
  (`scripts/under_load_power.py`), four rounds confirm U-a's growth clause, U-b and U-c, each in
  all four cells at once as the judge requires, in at least 94% of made-up blocks at the pilots'
  effects. With the load's excess over idle halved, they confirm in at least 83%. The plan's rule
  asks for 80%. U-a's real-time clause and U-d have no pilot, and rest on the floor of four.

## Predictions

A setup's value is the median over its passing runs of each run's statistic. A cell, one broker at
one rate, is out of reach where a setup it needs has no passing run or no value of the statistic.
It is reported, and the prediction is judged on the cells it reaches. A clause that fails fails
its cell, even where the cell's other clause cannot be read.

- **U-a (the turnaround grows under load, and real-time priority holds it):** at 500 and 2,000
  messages a second, on each broker:
  - `T_c`'s 99th percentile at 80% load and normal priority is at least 1.5 times its value idle;
  - at 80% load, its 99th percentile at real-time priority is at most half its value at normal
    priority.
- **U-b (the fix alone gives way where requests wait):** at 500 and 2,000 messages a second, on
  each broker, `W_so`'s 99th percentile at 80% load and normal priority is at least 1.5 times its
  value idle.
  - **Decision:** where U-b holds, the paper says that a pull consumer's kernel-timed latency does
    not hold still under load at that rate, on that broker.
- **U-c (removing the turnaround takes the thread's part out):** at each rate and broker where U-b
  holds, the share of U-b's rise that the turnaround removes is at least one half. With setup
  values of the 99th percentile, that share is
  `1 − (F_load − F_idle) / (W_so,load − W_so,idle)`. Where U-b does not hold there is no rise to
  take out, and the cell is not judged.
  - **Decision:** where the share is at least 0.9, the paper says that the consumer's turnaround
    carries the load into `W_so` at that rate, on that broker. Elsewhere it gives the share, and
    U-e's split of the rest.
- **U-d (real-time priority keeps the threads out):** at 80% load, at 500 and 2,000 messages a
  second, on each broker, `W_so`'s 99th percentile at real-time priority is at most half its
  value at normal priority.
- **U-e (where the rest lies, a decision rule):** at 500 and 2,000 messages a second, on each
  broker, take the rise of `F` from idle to 80% load at normal priority. Measure it as the mean
  over the messages above each setup's 99th percentile of `F`. That rise splits exactly into the
  three terms of the split.
  - **Decision:** the paper names the term that holds at least half of the rise. If no term does,
    it gives the split.
- **U-f (L-b's rise, a decision rule):** at 50 messages a second, on each broker, take the rise
  from idle to 88% load of the mean of `F` over each setup's messages. No message waits for a
  request at 50, so there `F` is `W_so`, and the rise splits the same way.
  - **Decision:** the paper names the term that holds at least half of it.
- **The pool U-e and U-f read:** a setup's messages, over its runs whose split reaches at least
  99.5% of their timed messages, and only the messages the split reaches.
- **Described, not judged:**
  - the medians of everything above, the split's terms per run among them;
  - the flagged share and the share of reads that drained more than one packet;
  - `|W_so − W|` against the captures;
  - the saving's bounds on each side, the client's `s_min` and `s_max` and the broker's, and each
    range's width;
  - what block U's extra instruments cost (the producer's journal, the card's capture and the
    broker's): its idle medians of `W_so` and of the end-to-end latency at 500 and 2,000 a second,
    less block L's idle medians at the same rates (`l_runs.csv`).

## Why these margins

- **U-a's 1.5 and one half, U-b's 1.5 and U-d's one half** repeat K-c's effect sizes, the ones
  freezes 39 to 41 asked of a thread's wait.
- **U-c's one half** asks the turnaround to be the main path, and 0.9 is the bar for the paper to
  say it is the only one. The pilots' shares, 0.68-1.01, are why the half is a test and the 0.9 a
  decision.
- **U-e's and U-f's one half** names a term only when it holds most of the rise.
- **The pool's 99.5%** is F-c's share of messages a capture may miss.

## What could go wrong, and what it would mean

- **80% may not hold beside the clients and the driver's three captures.** The pilot settles it. If it does not
  hold, every load setup at 500 and 2,000 takes the highest load the pilot held within 3 points at
  both rates, stated before any judged run.
- **Real-time clients may take processor time the load needs,** and fail the load check. The
  pilot settles it, under the same rule.
- **The broker's capture costs a two-processor broker time,** the same in every setup. Its cost is
  described against block L's idle runs.
- **The card may give no timestamps on this pair.** `Q` then folds into the first term, and the
  plan says so before any judged run.
- **The split's first term holds the network and the producer's sending path together.** Only its
  rise is read, and a rise there is not split further.
- **The saving is first-order.** A consumer that asked sooner would ask more often, and the broker
  might answer more slowly. That is not modeled.

## Pilot (instruments only; predictions above do not change)

One round of the sixteen setups, checking that:
- every run passes the integrity rule, or its failure is read for its instrument;
- every message is found in the broker's capture and in the card's, and no capture drops a
  packet;
- the card's device and clock are recorded;
- 80% load holds at both upper rates and at real-time priority.

The pilot's runs are not judged.
