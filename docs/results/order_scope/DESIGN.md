# Freeze 41 (plan version 44): the acknowledgment's own arrival, and where the kernel-timed latency holds

Draft written 15 October 2026, before any pilot or judged run of its blocks. What prompted it:
two referees of the paper's ninth version, reading independently, asked for the same
measurements.

- **The one rival the paper leaves open.** A broker that put the delivery on the wire before the
  acknowledgment would make S = t_recv − t_ack negative with no wait at all. The paper said so
  (its Section VIII) and said that a capture of both connections would settle it, and freezes 39
  and 40 built the instrument without logging the acknowledgment's arrival.
- **The kernel-timed latency's scope.** The fix (W, freezes 39 and 40) was shown at 50 messages
  a second only, with no positive control. At benchmark rates, a pull consumer's request cadence,
  receive processing deferred to a kernel thread, and reads that drain several packets could put
  client waits back into W.
- **Two checks of the timescale.** The scheduler's run-to-parity rule should be what makes a woken
  thread wait out the rest of a slice. A mode of negative values at −250 to −150 µs could instead
  be the wake of an idle processor.

**What we had read before this design, and what it informed.** On 15 October we read freeze 40's
own runs (`runs/azure/collected/matched/f2`). Its distribution of S showed three things:
- On Redis with no background load, 10.9% of S is below zero at normal priority and 17.9% at
  real-time priority, every value within 70 µs of zero (median −18 and −7 µs). That is what reply
  order with no wait would produce.
- On Redis at 88% load and normal priority, 1,479 of 4,824 negative values lie between −250 and
  −150 µs.
- On Kafka, negative values appear only under load at normal priority, and most lie below −500 µs.

These readings are why K-b is stated as a prediction for Redis at real-time priority, and why the
idle-processor block runs at 88% load. No other prediction below uses them.

## What is measured, per message

All on the driver's one clock, as in freezes 39 and 40.
- **From the clients:** `t_pub`, `t_ack` and `t_recv`.
- **From the captures:** `t_tx` and `t_rx` (freeze 39).
- **From the clients' sockets:** `t_tx_so` and `t_rx_so` (freeze 40).
- **New, from a journal of every read and write the clients make on their broker connections**
  (`scripts/so_timestamps.py --so-journal`):
  - **`t_rx_ack`:** the kernel's software receive timestamp of the producer's read that delivered
    the last byte of the message's acknowledgment.
    - *Kafka:* the acknowledgment is the produce response whose correlation id is that of the
      produce request that carried the message.
    - *Redis:* the acknowledgment is the reply to the XADD that carried the message. Replies come
      in request order on a connection, and the reply is the entry id the consumer later receives.
  - **`t_req`:** the kernel's transmit timestamp of the consumer's request that the message was
    delivered in answer to.
    - *Kafka:* the fetch request whose correlation id the fetch response carries.
    - *Redis:* the XREAD/XREADGROUP command whose reply delivered it.
  - **Packets per read:** for each consumer read, the number of the connection's incoming packets
    whose payload it drained, counted from the receiver's capture by TCP sequence number.

The journal writes each connection's bytes in each direction and one row per call:
- for a read: the stream offset after it and its receive timestamp;
- for each transmit timestamp: the byte offset of the last byte of its send call.

Everything else is computed after the run by `scripts/so_journal.py`. Each acknowledgment and each
request is matched to its message by the broker's own wire format, so the client libraries stay
unchanged.

**What is derived from them.**
- **Kernel-timed order:** `S_k = t_rx_so − t_rx_ack`. It is positive when the delivery reached the
  client machine after the acknowledgment, and no client thread's wait is in it.
- **The acknowledging thread's delay:** `δ_ack = t_ack − t_rx_ack`. This is the late reading
  itself, message by message.
- **The consumer's delay:** `δ_recv = t_recv − t_rx_so`.
- **An identity on one clock:** `S = S_k + δ_recv − δ_ack`. So S < 0 exactly when
  δ_ack − δ_recv > S_k.
- **The pull flag:** a message is flagged when `t_req > t_tx_so`, that is, when the request it was
  delivered in answer to left the client after the message itself left. Such a message waited in
  the broker for a request, and that wait is inside W.

## Blocks

Each block runs on one pair and tests its predictions within that pair. The base slice is 3 ms
and the broker has no added delay unless a block says otherwise. As in freezes 39 and 40:
- load is none or 88% stress-ng on the driver;
- priority is normal or real-time (SCHED_FIFO 80) for the producer and the consumer together;
- every run is judged by `scripts/run_integrity.py` as it ends, and only passing runs are read.

| Block | Pair | Setups | Rounds | Runs | Rate, duration |
|---|---|---|---|---|---|
| K, the acknowledgment's arrival | matched | 10 | 6 | 60 | 50 msg/s, 130 s (30 s warm-up) |
| R, run-to-parity | matched | 4 | 6 | 24 | 50 msg/s, 130 s |
| P, positive control | matched-b | 6 | 4 | 24 | 50 msg/s, 130 s |
| L, rate ladder | matched-b | 4 per rung, 3 rungs | 4 | 48 | 50, 500, 5,000 msg/s; 70 s (20 s warm-up) |
| I, idle processors | matched-b | 4 (two boots) | 4 | 16 | 50 msg/s, 130 s |

- **K:**
  - freeze 40's eight setups (Kafka and Redis, no load or 88%, normal or real-time priority), with
    the socket timestamps taken at the device queue, the journal on both clients, the receiver's
    capture, and both directions of the producer's connection captured (to check `t_rx_ack`
    against the capture);
  - two more setups: Redis at real-time priority with one send worker instead of sixteen, idle and
    at 88%.
- **R:** Kafka and Redis at 88% load and normal priority, with the scheduler's RUN_TO_PARITY
  feature on (the kernel's default) or off (NO_RUN_TO_PARITY, set through debugfs before each run
  and checked after). Socket timestamps and journal as in K.
- **P:** Kafka and Redis, no load, normal priority, with a delay of 0, 1 or 2 ms added on the
  broker's path to the receiver only (the receiver-only delay of the registered campaign). Socket
  timestamps and both captures.
- **L:** Kafka and Redis, no load or 88%, normal priority, in three campaigns at 50, 500 and 5,000
  messages a second.
  - If the pilot finds that the clients cannot hold 5,000 a second within the integrity rule, the
    top rung is 2,000, and the plan says so.
  - Socket timestamps; the consumer's journal; both captures.
- **I:** Kafka and Redis, 88% load, normal priority, on the stock kernel's default boot and on a
  boot with `idle=poll` on the kernel command line, so that an idle virtual processor spins
  instead of halting.
  - The boot is selected once, with grub-reboot, by the pair's own work list. The default-boot runs
    come first.
  - Socket timestamps and journal as in K.

## Predictions

A setup's value is the median over its passing runs of each run's statistic over its messages,
unless the prediction says it pools messages.

**K, the acknowledgment's arrival**
- **K-v (the journal agrees with the capture):** in every setup, the median over runs of each
  run's median of |`t_rx_ack` − the capture's arrival timestamp of that acknowledgment| is at most
  20 µs.
- **K-a (Kafka, the rival is excluded):** in every Kafka setup with at least 20 negative values of
  S, at least 90% of the messages with S < 0 have S_k ≥ 0, pooled over the setup's runs. Kafka
  sends the produce response before it completes waiting fetches when the append raises the high
  watermark (Referee A's reading of `ReplicaManager.scala`), so a negative S on Kafka should be a
  late reading.
- **K-b (Redis, the rival is real where no thread waits):** in Redis's two real-time setups with
  sixteen workers, at least half of the messages with S < 0 have S_k < 0, pooled. Redis writes the
  delivery to a blocked consumer before the producer's reply in the same pass of its event loop
  (Referee A's reading of `server.c` and `networking.c`), and freeze 40's real-time negatives lie
  within 70 µs of zero.
- **K-b, described:** for every Redis setup, Pr[S_k < 0] and the share of negative S with
  S_k < 0. **Decision:** the paper attributes to reply order exactly the share of each broker's
  negative S that has S_k < 0, and to late reading the rest.
- **K-c (the late reading is the acknowledging thread's wait for a core):** on both brokers:
  - with sixteen workers on Redis, the 99th percentile of δ_ack at 88% load and normal priority is
    at least 1.5 times its value idle;
  - at 88% load, its value at real-time priority is at most half its value at normal priority.
- **K-d (Equation 3, message by message):** in each broker's setup at 88% load and normal priority:
  - pool the messages with S_k ≥ 0 and bin them by S_k into quintiles;
  - the observed Pr[S < 0 | bin] is non-increasing from the lowest quintile to the highest;
  - in every quintile with at least 20 negative values, it lies within a factor of two of the
    prediction Pr[δ_ack − δ_recv > S_k]. That prediction is evaluated at each message's S_k from
    the setup's own distribution of δ_ack − δ_recv, taken as independent of the margin.
- **K-d, described:** the paper's p·G(S_k), with G the rest-of-a-slice survival of Fig. 3 for
  s = 3 ms and the tick, and p = Pr[δ_ack > 0.1 ms].
- **K-e (the interpreter lock, a decision rule):** in each of the two one-worker Redis setups, the
  rate of S < 0 is compared with the sixteen-worker setup at the same load.
  - If it is at most half, the paper says that the interpreter lock sets at least half of Redis's
    rate at real-time priority.
  - Otherwise it says the lock does not.
  - The share of negative S with S_k < 0 is reported beside it.

**R, run-to-parity**
- **R-a:** on both brokers, the rate of S < 0 with NO_RUN_TO_PARITY is at most two-thirds of the
  rate with RUN_TO_PARITY.
- **R-b:** on both brokers, the 99th percentile of δ_ack with NO_RUN_TO_PARITY is at most
  two-thirds of its value with RUN_TO_PARITY.

**P, positive control**
- **P-a:** on each broker, the median of W_so rises with the added delay, by between 0.9 and
  1.1 ms per ms added: the least-squares slope through the three setup medians.
- **P-b:** on each broker, the median of the publish latency A, whose path the delay does not
  touch, moves by at most 10% between any two delays.
- **P-c:** on each broker, the median of D rises by between 0.9 and 1.1 ms per ms added.

**L, rate ladder**
- **L-a:** at every rung, in every setup, the median over runs of each run's median of
  |W_so − W| is at most 20 µs.
- **L-b:** at every rung and on each broker, W_so's median at 88% load lies within 10% of its
  median idle. Where it does not, the paper scopes the fix to the rungs where it does.
- **L-c:** at 50 messages a second, at most 1% of messages carry the pull flag in every setup.
- **L-c, described:** at every rung,
  - the flagged share;
  - W_so's median for flagged and unflagged messages;
  - the share of consumer reads that drained more than one packet;
  - the rate of S < 0.

**I, idle processors (a decision rule)**
- On Redis, the share of negative S between −250 and −150 µs is compared across the two boots.
  - If `idle=poll` cuts it at least in half, the mode is the wake of an idle processor, and the
    paper says so.
  - Otherwise it says it is not.
- Described: δ_ack's median and its share above 100 µs under each boot, on both brokers.

## Why these margins

- **K-v and L-a** repeat freeze 40's G-a. Where the acknowledgment and the delivery come in
  different packets, the journal's receive timestamp is the kernel's own stamp on the packet that
  completed the read.
- **K-a's 90%** is the share a "late reading" reading must explain to keep its name.
- **K-b's half** is a deliberately weak bar for a mechanism two independent sources point to.
- **K-c's 1.5 and one half** repeat the effect sizes freezes 39 and 40 required of D.
- **K-d's factor of two** is the registered campaign's factor of 1.5 widened, because quintiles
  of one setup hold fewer messages than a condition.
- **R's two-thirds** asks for an effect a reader would notice, not a threshold at the noise.
- **P's ±10% around one-for-one** is the precision freeze 40's setups gave W, about 3–8% at the
  median.
- **L-b** repeats F-a's 10% at the rungs a benchmark runs.

## What could go wrong, and what it would mean

- **Kafka's responses go out through network threads**, and the produce and fetch responses of one
  append may leave on different threads. K-a then fails, and the paper says what share of Kafka's
  negative S is reply order.
- **At 5,000 a second the Python clients may not keep the rate**, with the journal copying every
  byte. The pilot settles the top rung, and the integrity rule judges every run.
- **The journal costs the clients time.** That cost falls in H_out and H_in, not in W_so or S_k,
  which run between the kernel's timestamps; δ_ack and δ_recv include it. The cost is reported
  against freeze 40's runs, described and not judged.
- **A grub-reboot that does not come up** is recovered by the pair's work list. Its boot is
  verified from `/proc/cmdline` before any run of block I.

## Pilot (instruments only; predictions above do not change)

- **K and R:** one round of their setups. Every run writes both journals, every acknowledgment
  and request is matched, and `t_rx_ack` is compared with the capture.
- **L:** one run per rung on each broker, to settle the top rung.
- **I:** one boot with `idle=poll`, verified, and one run.

The pilot's runs are not judged.
