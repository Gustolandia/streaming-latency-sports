# The general method, tested (freeze 44, plan version 47)

This folder holds plan version 47's design and, as they come, its runs' records and verdicts. The
design is [`DESIGN47.md`](DESIGN47.md), fingerprinted in [`DESIGN47.sha256`](DESIGN47.sha256) and
frozen with the plan in [`freezes/44-experiment-plan/`](../../../freezes/44-experiment-plan/). Its
predictions were written, and fingerprinted, before any of its runs, the pilot included.

## What it tests

A method for timing message latency beneath any client, with a check built in:
1. **Kernel timestamps on the client machine, for every packet.** They come from the sockets where
   the language allows. Otherwise they come from a packet capture on the client host, with no change
   to the client. Each message is named by the broker's own id.
2. **A check any tool can run from those timestamps:** was a request waiting at the broker when each
   message arrived? The share that found none is reported beside the latency.
3. **Three latencies, each named:**
   - F: what the broker and network deliver to a ready receiver;
   - W: what reaches the client's kernel;
   - D: what reaches the application.
4. **A remedy that depends on the protocol.**

## The blocks

| Block | Design | What it tests |
|---|---|---|
| V | [`gv_design.json`](gv_design.json) | Redis with requests kept waiting (depth 1 and 256; one reply per read, and the library's own reads) |
| N | [`gn_design.json`](gn_design.json) | NATS JetStream with requests kept waiting (our pull consumer at depth 1 and 256; nats.go's `Consume()`) |
| P | [`gp_design.json`](gp_design.json) | RabbitMQ with credit (prefetch 1 and 1,000) |
| K | [`gk_design.json`](gk_design.json) | Kafka's real clients: kafka-python, Java, franz-go and librdkafka, and librdkafka's broker thread alone at real-time priority |
| C | [`gc_design.json`](gc_design.json) | the consumer's thread alone on its core: baseline, sibling idle, sibling loaded |
| S | [`gs_design.json`](gs_design.json) | scope probes, described only: a normal-priority producer; a load heavy in softirq work |
| A | [`ga_design.json`](ga_design.json) | the Arm pair's replication of V and of librdkafka |

The pilot, round a, is [`gpilot_x86_design.json`](gpilot_x86_design.json) and
[`gpilot_arm_design.json`](gpilot_arm_design.json): one run of each setup, instruments only, never
judged. Each judged setup's duty is written into its design only after the pilot, by the record
below.

## How it is run

On each pair, from its own work list (`cloud/azure/queue.sh`):

```
python3 scripts/run_queue.py make --design docs/results/general_method/gpilot_x86_design.json \
    --out runs/azure/queues/gpilot_x86.csv
```

The judged blocks' queues are made the same way, one per block, once the pilot's statements are
public.

## How it is read

The check's allowance per broker comes from the pilot's own broker captures, before any judged run,
one file for each pair (`allowance_x86.json` below; `allowance_arm.json` with the Arm pair's addresses,
10.1.1.30, 10.1.1.41 and 10.1.1.31):

```
python scripts/general_method.py calibrate --runs <pilot runs folder> [--runs ...] \
    --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 \
    --out docs/results/general_method/allowance_x86.json
python scripts/general_method.py read --runs <runs folder> [--runs ...] \
    --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 \
    --allowance docs/results/general_method/allowance_x86.json \
    --out-runs docs/results/general_method/g_runs.csv
python scripts/general_method.py judge --runs-table docs/results/general_method/g_runs.csv \
    --out docs/results/general_method/g_verdicts.json
```

The pilot's runs are read with `--pilot` and never judged.

## The record

Registered on 23 October 2026 by the push of `0661ba7c`, before any of its runs.

### Pilot round a (23 October 2026: instruments only, never judged)

One run of each setup was asked for, and every attempt is kept:
- on the x86 pair, its work list's jobs 229 to 233 (`gpilot_x86`, `gpilot_x86_b`, `gpilot_x86_c` and
  `gpilot_x86_d`);
- on the Arm pair, its jobs 57 to 62 (`gpilot_arm`, `gpilot_arm_b`, `gpilot_arm_c3`, `gpilot_arm_d`
  and `gpilot_arm_e`).

Each campaign was copied home and checked file by file (`runs/azure/collected/matched-b/` and
`runs/azure/collected/arm/`). Job 59 on the Arm pair was given a queue file with no rows, ran none
and was taken off the list, as was its copy the list put back (job 61). The x86 pair's job 231 was paused at 06:48 UTC to free its disk and
stood paused until 11:02. Its one run then in progress, `P2000-rabbitmq-p1-pilot-a2`, kept its
captures and its load running for 4.5 hours, and it is not read. The list ran the same queue again
as job 232.

**Found, and put right before any judged run.**
- RabbitMQ's command-line tools ran as root before the broker was up. They wrote the Erlang cookie
  as root, and the broker, which runs as `rabbitmq`, could not read it and stopped. They now run as
  the broker's own user (`c0889062`).
- librdkafka's consumer subscribed before its topic existed and read nothing in its 70 s. It now
  makes its topic first. The consumers that are not Python run without the thread counters they
  cannot sample. Block C's isolated arms run their load at their share of the machine. The Arm pair
  starts at a duty of 79 (`1ba71887`).
- The broker's capture is written to the broker's memory, not its disk (`f9d9f217`). On the Arm
  pair, whose broker writes to a slower disk, all seven Kafka runs with the capture on that disk had
  their acknowledgements held for 190 to 610 ms, about 30 s and 60 s into the capture. The producer
  fell behind and failed the lateness rule. With the capture in memory, both Kafka runs held the
  producer's lateness within 1 ms at the 99th percentile.
- The readers named no message by its payload's event id on any run of this version. The Poisson
  plans call their events `poisson-000000` and on, and the readers looked for `constant-` ids alone.
  They now read every arrival process the plan maker names (`recv_wait.EVENT_ID`). M1-b's check of
  the broker's ids against the payload's is read with that. The clients' own socket ledgers, which
  name messages the same way, were left as the pilot ran them. Every reading this version judges
  from the sockets comes from the clients' journals, matched by the broker's ids.

**Not put right, and left out under D47-11 with the reason.**
- **S2000-redis-prodnormal.** Its producer runs at normal priority under the load by design, and
  in its pilot run it fell 242 ms behind its schedule. The lateness rule of version 46, which this
  version holds every run to, forbids that, so the setup cannot run as designed. Block S keeps its
  other setup. Its pilot run is kept as what that probe saw: the load held 72.2%.
- **A2000-redis-d1 and A2000-redis-d256.** On the Arm pair, the Python producer did not keep
  2,000 messages a second under the load.
  - The first three Redis runs held the lateness rule, with spreads of 2.4 to 8.2 ms. Their broker
    capture was written to disk.
  - All seven runs after the capture moved to memory failed it, with spreads of 27 to 892 ms.
  - By the broker's own capture, its median time from an XADD's arrival to its reply's departure
    was 41 to 54 µs, before the move and after (99th percentiles 122 to 139 µs, in the three runs
    read for it). So the time was lost outside the broker, and the cause is not known.
  - The producer kept 16 threads sending, each waiting for its reply, behind one interpreter lock.
    Handing that lock every 0.5 ms instead of CPython's 5 ms changed neither the replies' times nor
    the failures (`99715310`, taken back in `09d01392`). The x86 pair's Redis runs of job 233
    ran with that interval too and passed; they set no value below, which comes from the runs
    of jobs 229 to 232.
  - Block A keeps librdkafka's two setups. Of A's three parts, V-a and M2-c on Redis are out of
    reach; KC-d is judged on the Arm pair. The Arm pair's card gives no hardware timestamps, so
    M1-a has no cell there either.

**Block C** is amended by plan version 48 before any judged run of it. Its pilot runs showed the
registered placement cannot hold on this testbed:
- One card carries both clients' traffic and three captures. With the receiver's interrupts on the
  consumer's own vCPU, all of them landed there. The consumer at real-time priority then ran at the
  throttle's 95% of that vCPU, counting the receive path's work, which this kernel charges to the
  task it interrupts.
- In one run its producer fell 388 ms behind.
- In the other, the consumer read nothing: its heartbeat thread, at the same priority on the same
  vCPU, never ran, and the broker removed it from its group after 10 s.

Version 48's own pilot comes before its judged runs, which run after block S.

**Seen beside the predictions, which do not change.** With its capture in memory, the Arm pair's
broker still stalls now and then. In both runs of librdkafka with its broker thread at real-time
priority, one stall fell in an off-block:
- the off-blocks' tail means of `W`, and of `F`, the latency to a ready receiver, were 64 and
  120 ms;
- the on-blocks' were 1.2 to 2.5 ms;
- the consumer's turnaround stayed within 64 µs.
`W`'s tail ratio is then set by where the broker's stalls fall. So KC-d on the Arm pair, and any
equivalence clause in a run where a stall falls in one load state, can fail for that reason alone.
The record of the verdicts will say where it did.

**Stated before any judged run (D47-11).**
- **Each loaded setup's frozen duty**, now `duty_pct` in each judged design. It is the starting duty,
  corrected by the median miss of the setup's pilot runs where any of them missed 70% by more than
  3 points:

  | Setup | Duty | On-block load in its pilot runs |
  |---|---|---|
  | V2000-redis-d1, -d256, -d256-lib | 75 | 67.4-68.1% |
  | N2000-nats-d1, -d256, -go | 75 | 71.9-72.7% |
  | P2000-rabbitmq-p1 | 72 | 73.0% and 72.5% at 75; 69.7% at 72 |
  | P2000-rabbitmq-p1000 | 75 | 72.1% |
  | K2000-kafka-python, -java, -franz, -rdk, -rdk-rt | 75 | 69.5-71.4% |
  | S2000-redis-udp | 82 | 57.7%, 63.0% and 63.1% at 75; 68.3% at 82 |
  | A2000-kafka-rdk, -rdk-rt (Arm pair) | 73 | 75.3-75.9% at 79; 71.2-71.9% at 73 |

  The judged runs replay the Poisson draw the designs' job line gives them, make_synthetic_plan.py's
  default seed of 12345. The pilot replayed seed 20261105.
- **The check's allowance per broker**, from the pilot's broker captures (`scripts/general_method.py`'s
  calibrate over every passing pilot run where it has a value): on the x86 pair, Kafka 60 µs in the
  capture and 45 µs in the sockets, Redis 15 µs in both, NATS and RabbitMQ 0
  ([`allowance_x86.json`](allowance_x86.json)); on the Arm pair, Kafka 80 µs in the capture
  ([`allowance_arm.json`](allowance_arm.json)).
- **The brokers, as pinned:** Redis 7.4.11 and RabbitMQ 4.3.7 by their image digests, Kafka 4.1.1,
  and NATS 2.15.1 with JetStream, in every run's `broker_facts.json`.
- **The consumers' threads, as `/proc` names them:** Java's poll loop `law-poll`, which fetches;
  librdkafka's `rdk:broker1`, the one thread that fetches, beside `rdk:main`; franz-go's threads all
  `franz-consumer`, none of them alone at fetching, so only its whole process can be raised.
- **The instruments, in every run read** (16 on the x86 pair and 2 on the Arm pair, under the
  final instruments: [`gpilot_runs_x86.csv`](gpilot_runs_x86.csv),
  [`gpilot_runs_arm.csv`](gpilot_runs_arm.csv)):
  - every message was found in the broker's capture by its id and paired by the broker's ids on
    the client host, none sent or received alone and none unread, and no capture dropped a packet;
  - the payload's ids paired every message the broker's ids paired, and none differently;
  - the certain reading called no message unwaited that the broker shows waiting;
  - in every setup that keeps requests or credit waiting, the broker's record shows one waiting
    for every message: Redis serves a queued request in the same pass at depth 256, NATS keeps 256
    requests waiting, and RabbitMQ keeps a credit waiting at 1,000;
  - on the x86 pair, the card's lag `Q` had its 99th percentile at 14 to 93 µs.
- **The rounds: four.** `scripts/general_method_power.py`, the rule of version 45 through the
  registered judge, 2,000 made-up blocks per scenario, seed 20261104 ([`g_power.json`](g_power.json)):
  - At the pilot's values the judge confirms M1-b, M2-a, M2-c, KC-a and KC-b in every made-up block
    at four rounds, and with the load's excess halved.
  - M2-b clears its margin at the pilot's values: each run's estimate was within 3.1 points of the
    broker's share. But the rule draws a run's two shares apart, and under that no number of
    rounds up to twelve confirms it in 80% of blocks (none at four). It is reported at four.
  - M1-a, M1-c, M3-a, M3-b, KC-c, KC-d, KC-h and A do not clear their margins at the pilot's
    values. They rest on the floor of four, their power stated: none at four, KC-h 0.9%.
  - The same with each tail ratio drawn at the spread the pilot's own repeated runs show is
    described in [`g_power_pilot_spread.json`](g_power_pilot_spread.json). It asks the same rounds.
- **Where the pilot's values miss their margins.** The judged runs decide these; no margin changes.
  - M1-a: `Q`'s 99th percentile was within its bound in every x86 run, but in 3 of 16 runs some
    packets read as reaching the kernel before the card stamped them (`Q` down to -40 µs). The
    clause allows -1.5 µs, the card clock's window.
  - M1-c: at depth 256 with one reply per read, the sockets' 99th percentile of `W` sat 2.2 to
    3.6 ms above the capture's. The clause asks for within 10 µs; at depth 1 they agreed within
    6 µs.
  - M3-a (V-a, N-a, P-a): where requests or credit waited, `W`'s tail held still on Redis and NATS
    (on/off ratios 0.86 to 1.03), and RabbitMQ's at 1,000 fell to 0.74. But `D`'s ratio was 1.11
    to 1.49 on Redis and NATS, short of 1.5.
  - M3-b: `W`'s tail rose for Redis at depth 1 (2.25) and the in-poll Kafka clients (1.86 to 4.64),
    and removing the turnaround took out more than half of each rise. NATS's and RabbitMQ's
    gapped setups did not rise (0.93 and 1.02).
  - KC-c: librdkafka's rise of the turnaround at normal priority, 3.1 ms, is under half of
    kafka-python's (8.8 and 10.6 ms) but not of Java's 3.4 ms or franz-go's 3.7 ms.
  - KC-d: with only its broker thread at real-time priority, librdkafka held `W`'s tail still on the
    x86 pair (0.93), but `D` did not grow (1.01). On the Arm pair, a broker stall in an off-block
    set the ratio (0.01).
  - KC-h: the turnaround's on/off ratio was 1.38, and 41% of messages found no fetch waiting in
    the on-blocks.
  - M2-c's client clause: the checks of `B` held for Redis and NATS. For RabbitMQ they failed on
    silences of 15 and 17 ms on the delivering connection, longer than `B`, so the clause may stay
    out of reach there.
