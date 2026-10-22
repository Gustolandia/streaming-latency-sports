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
    --out-runs docs/results/under_load/u_runs.csv --out-tails docs/results/under_load/u_tails.csv
python scripts/under_load.py judge --runs-table docs/results/under_load/u_runs.csv \
    --tails-table docs/results/under_load/u_tails.csv --out docs/results/under_load/u_verdicts.json
```

## Where it stands

Registered on 22 October 2026 (pushed at 01:53 UTC). The pilot, its reading and the block's runs are
recorded here as they happen.

## The pilot

Instruments only, never judged; the predictions do not change.

**First round** (22 October, from 01:57 UTC, `up2000`, `up500`, `up50`). Every idle run passed the
integrity rule, every capture reported no packet dropped, the card's clock was sampled through its
own device, and the producer's journal was kept. An 80% load did not hold beside the clients and
the driver's three captures at 2,000 messages a second: it measured 75.8% on Kafka at normal priority, 69.1%
at real-time priority and 76.3% on Redis, whose producer also fell to 1,877 messages a second. The
campaign stopped itself, by its guard, after those three attempts, before Redis's real-time setup.

**Second round** (`up2000b`, `up500b`). As D45-7 provides, the loaded setups at both upper rates
run again at 70%, just above the least load the first round measured, to find whether it holds
within the integrity rule's 3 points at both rates and priorities and whether Redis's producer then
keeps its rate.
