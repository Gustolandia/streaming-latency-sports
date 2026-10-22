# Freeze 42: the consumer's turnaround, where load and rate bite together

A pull consumer, which asks the broker for each batch, lets its own thread's time back into the
kernel-timed latency of freezes 39 to 41: a message the broker holds while no request is waiting
leaves only with the next request, and that request leaves after the consumer's thread turns
around. Freeze 41 judged the kernel-timed latency under load at 50 messages a second only, because
an 88% load could not be held beside the clients at 500 and 2,000. Freeze 42 tests the fix and the
turnaround at 500 and 2,000 messages a second under load, and places what remains at the broker
and at the network card. Its plan is frozen in
[`freezes/42-experiment-plan`](../../../freezes/42-experiment-plan/) (plan version 45), and its
predictions were written, and fingerprinted, before any of its runs, the pilot included
([`DESIGN.md`](DESIGN.md), [`DESIGN.sha256`](DESIGN.sha256)).

*Words in this part.* **Turnaround**: the consumer's own time from the moment the kernel holds the
broker's answer to the moment its next request leaves; its thread's work and any wait for a core.
**Thread-free latency**: the kernel-timed latency less what the turnaround surely added.
**Residence**: a message's time inside the broker, from the arrival of the request that carried it
to the departure of the answer that delivered it, on the broker's own clock.

## What is measured

Beside freeze 41's times, each message carries:

| Time | Where it comes from |
|---|---|
| the turnaround `T_c` before the request that delivered it | the consumer's journal: the request's transmit timestamp less the previous answer's receive timestamp, on one socket |
| the thread's saving, between `s_min` and `s_max` | the journals: no client clock sees when the broker could hand the message out, so the saving is bounded, exactly where the acknowledgment came in before the previous answer |
| `P_in`, `A_out`, `F_in`, `R_out` | the broker's own capture of its port, on the broker's clock, differences only |
| `t_card` | the card's receive timestamp, put on the system's clock |

On one identity, the thread-free latency `F = W_so − s_min` splits into the network crossings with
the producer's sending path, the broker's residence less the thread's saving, and the consumer
kernel's receive processing, each a difference of durations read on one clock. `DESIGN.md` gives
every definition.

## The block

| Rate | Setups on each broker | Runs |
|---|---|---|
| 2,000 msg/s | idle; 80% load; 80% load at real-time priority | 24 |
| 500 msg/s | idle; 80% load; 80% load at real-time priority | 24 |
| 50 msg/s | idle; 88% load | 16 |

All on the second x86 pair, 70 s per run with a 20 s warm-up, every run with the socket
timestamps, both journals, both client captures, the card's capture and the broker's capture. The
queues are made from [`u2000_design.json`](u2000_design.json), [`u500_design.json`](u500_design.json)
and [`u50_design.json`](u50_design.json); the pilot's from `up2000`, `up500` and `up50`.

| Prediction | What it says |
|---|---|
| U-a | under load the turnaround's 99th percentile grows at least 1.5-fold, and real-time priority halves it |
| U-b | the fix alone gives way: the kernel-timed latency's 99th percentile grows at least 1.5-fold under load |
| U-c | removing the turnaround takes out at least half of that rise; at 0.9 the paper calls it the only path |
| U-d | under load, real-time priority halves the kernel-timed latency's 99th percentile |
| U-e, U-f | decisions: the term of the split that holds at least half of what remains, at 500 and 2,000 in the tail and at 50 in the mean |

## How it is read

```
python scripts/under_load.py read --runs runs/azure/collected/matched-b/u2000/runs \
    --runs runs/azure/collected/matched-b/u500/runs --runs runs/azure/collected/matched-b/u50/runs \
    --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 \
    --out-runs docs/results/under_load/u_runs.csv --out-tails docs/results/under_load/u_tails.csv \
    --out-attempts docs/results/under_load/u_attempts.csv
python scripts/under_load.py judge --runs-table docs/results/under_load/u_runs.csv \
    --tails-table docs/results/under_load/u_tails.csv \
    --attempts-table docs/results/under_load/u_attempts.csv \
    --ladder-table docs/results/order_scope/l_runs.csv --out docs/results/under_load/u_verdicts.json
```

## Where it stands

Registered on 22 October 2026 (pushed at 01:53 UTC), and amended by plan version 46 before any
judged run ([`DESIGN46.md`](DESIGN46.md), freeze 43; see the last section). The pilot, its reading
and the block's runs are recorded here as they happen.

## The pilot

Instruments only, never judged; the predictions do not change.

**First round** (22 October, from 01:57 UTC, `up2000`, `up500`, `up50`). Every idle run passed the
integrity rule, every capture reported no packet dropped, the card's clock was sampled through its
own device, and the producer's journal was kept. An 80% load did not hold beside the clients and
the driver's three captures at 2,000 messages a second: it measured 75.8% on Kafka at normal priority, 69.1%
at real-time priority and 76.3% on Redis, whose producer also fell to 1,877 messages a second. The
campaign stopped itself, by its guard, after those three attempts, before Redis's real-time setup.

The rest of the first round: at 500 messages a second 80% held on Kafka at normal priority
(77.3%) and on Redis at both priorities (78.4%, 77.7%), and not on Kafka at real-time priority
(74.3-74.8%, three attempts); at 50 a second every run passed, the 88% load held at 87.1-87.7%.

**Second round** (`up2000b`, `up500b`). As D45-7 provides, the loaded setups at both upper rates
ran again at 70%, just above the least load the first round measured. 70% held at both rates at
normal priority (68.0-69.5%, Redis's producer keeping 2,029 messages a second) and at 500 a second
at real-time priority (67.1%, 68.4%), and not at 2,000 a second at real-time priority: 63.3% and
63.4% on Kafka, 64.5% on Redis, the campaign again stopped by its guard. The machine was not full:
it was 78-86% busy, the clients' own share 13-23%. The duty is corrected once before the clients
start, and clients sending 2,000 messages a second at real-time priority cost stress-ng's duty
cycle more time than they use.

**Third round** (`up2000c`, `up500c`). An instrument change, made in the pilot and before any judged
run: where a setup asks (`load_recorrect`), the duty is corrected a second time, ten seconds into
the trial and inside its warm-up, against the background load the machine then shows less the
clients' own share, which is what the integrity rule reads (`cloud/azure/campaign.sh`,
`recorrect_load`). The same eight setups run again at 70% with it. 75% is not tried: at 76% Redis's
producer already fell behind its rate in the first round. All eight passed: 69.7%, 67.5%, 70.0% and
69.2% at 2,000 messages a second (Kafka and Redis, normal and real-time priority), 70.4%, 69.3%,
69.5% and 70.3% at 500, the duty corrected to 70-77% and the send rate kept.

**What the pilot read.** Read with `scripts/under_load.py read --pilot`, every passing run's timed
messages were all found in the broker's capture and in the card's (100.0% in each of its 25
passing runs), no capture dropped a packet, the split reached every timed message, and the
sockets agreed with the captures within 1.2-3.0 µs at the median.

**The decision, before any judged run (D45-7).** 80% did not hold; 70% held within the integrity
rule's 3 points in every loaded setup at both upper rates once the duty is corrected with the
clients running. So every load setup at 500 and 2,000 messages a second runs at 70% with
`load_recorrect` (`u2000_design.json`, `u500_design.json`, their ids `-l70` and `-l70-rt`). The 50
messages a second campaign keeps its 88% and its instruments, which held in the first round. The
predictions, their margins and the table's run counts do not change.

## Version 46: the block amended before any judged run

After the pilot and before any judged run, the design was checked against the pilot's own runs.
The check found that several quantities the predictions read would not mean what their names say.
Plan version 46 (freeze 43, [`DESIGN46.md`](DESIGN46.md), fingerprinted before its own pilot round)
amends the block and changes no margin. In brief:

| Found in the pilot | What changes |
|---|---|
| Under load, Redis's producer at 2,000 a second sent a median of 24 ms late (272 ms at the 99th percentile), in runs the integrity rule passed | the producer at real-time priority in every setup, so only the consumer's priority varies; a lateness rule in the integrity check |
| The clients paused 17-84 ms at about 24, 34, 46 and 60 s into every run, as CPython's full collections would | the collectors off once the clients connect, and logged; two runs keep them on, to check the cause |
| The first run after a broker start was the one in which Kafka created its offsets topic, and it alone moved U-c's Kafka-2,000 share from 0.83 to 1.00 | a priming run on each broker before each campaign |
| The real-time setups ran stress-ng 4-5 points harder, set by a correction that assumes a gain it does not have | each loaded setup's duty frozen from the pilot, and the runs open-loop |
| Redis's acknowledgment batches fell outside the turnaround, and their messages filled 85-95% of `F`'s tail | the turnaround from the previous request for messages, less the connection's other requests; their wait a term of its own |
| Each TCP connection keeps its own network delay, about 330, 500, 590 or 655 µs | each connection pair's floor taken out of the split; U-f compared within runs whose load runs in 5-s blocks |
| `s_min` leaves the request's and the acknowledgment's crossings in, and U-c's share was a difference of percentiles | the broker's tighter bound in U-e's split; U-c's share from tail means, with a run-level interval |

**Words in this part.**
- **Lateness**: a message's send time less its planned time.
- **Floor**: the fixed delay of a pair of connections.
- **Duty**: the share of time stress-ng is asked to compute.

**Pilot round d** (22 October, from 17:18 UTC; `up2000d`, `up500d`, `up50d`, and the collector runs
`ug2000`). Instruments only, never judged. It ran under version 46 after the push that made it public
(`a4bfe285`), each campaign primed on both brokers first. All 18 runs passed the integrity rule. One
attempt failed it: Kafka at 70% load at 500 a second, where the producer's lateness spread 286 ms
between its 1st and 99th percentiles, about half a second of sends held back once. Its repeat passed
at 0.02 ms, and the failed attempt is kept and described. Read with `scripts/under_load.py read
--pilot` into [`upd_runs.csv`](upd_runs.csv), [`upd_tails.csv`](upd_tails.csv) and
[`upd_attempts.csv`](upd_attempts.csv):
- **Instruments.** Every timed message is split, and found in the broker's capture and in the card's,
  in all 16 passing runs. No capture dropped a packet, and the sockets agreed with the captures
  within 1.2-3.0 µs at the median.
- **The load.** The loads held at 67.2-70.2%.
- **The producer.** It ran at real-time priority in every setup: every thread of the Python
  producer at SCHED_FIFO 80, and the consumer at SCHED_OTHER except in the real-time setups, as
  `run_facts_clients.json` records. Its lateness spread was at most 0.54 ms in every passing run,
  against 108-272 ms for Redis under load in freeze 42's pilot.
- **The collectors.** Off, with no collection in any run.
- **The consumer thread's own counters.** Under load at normal priority, 27-47% of its turnaround
  time was spent waiting for a core; at real-time priority, 0.02-0.11%.
- **The 50-a-second blocks.** 86.7% and 87.6% while on, and 0.03% and 0.06% while off.

**Stated before any judged run (D46-11).**
- **Each loaded setup's frozen duty**, the duty its passing pilot run used with the second
  correction, now `duty_pct` in [`u2000_design.json`](u2000_design.json) and
  [`u500_design.json`](u500_design.json):

  | Rate | Kafka, normal | Kafka, real-time | Redis, normal | Redis, real-time |
  |---|---|---|---|---|
  | 2,000 msg/s | 75 | 77 | 75 | 75 |
  | 500 msg/s | 71 | 73 | 71 | 72 |

  The 50-a-second blocks keep their duty of 88, which held.
- **The rounds: four.** `scripts/under_load_power.py --pilot-table upd_runs.csv`, 20,000 made-up
  blocks per scenario.
  - At the pilot's effects, the clauses confirm, each in all four cells at once: U-a's growth
    clause in 100%, its real-time clause in 100%, U-b in 98.6% and U-c in 99.6% of blocks, against
    the rule's 80%.
  - U-d does not clear its margin in every cell at the pilot's means, so it rests on the floor of
    four: its power is 22%.
  - With the load's excess over idle halved: U-a 100% and 97.1%, U-b 53.9%, U-c 92.4%, U-d 2.2%.
- **The pilot's values of U-a's real-time clause and of U-d.**
  - U-a's real-time clause: the turnaround's 99th percentile at real-time priority over its value at
    normal priority, 0.13 (Kafka, 2,000), 0.21 (Redis, 2,000), 0.21 (Kafka, 500) and 0.11 (Redis,
    500).
  - U-d: `W_so`'s 99th percentile at real-time priority over its value at normal priority, 0.19,
    0.58, 0.24 and 0.22. At Redis's 2,000 it is above U-d's margin of at most 0.5.
- **The pauses were the collector's.**
  - In the two runs that kept it on and logged it, each consumer made six turnarounds over 10 ms
    (the longest 58.4 and 73.2 ms), and five of each six fell on a logged collection, whose longest
    full collections took 57.6 and 72.7 ms.
  - In round d's idle runs at the same rate with the collector off, there was no turnaround over
    10 ms and no collection.
  - In freeze 42's, with the collector on, there were five, of up to 45 and 58 ms.
- **The failure rules.** None fired:
  - the lateness rule failed one attempt, and its repeat passed, so no rate failed it at 70%;
  - the blocks held 88%;
  - every client ran with its collector off.
