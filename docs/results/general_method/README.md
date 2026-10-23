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

The check's allowance per broker comes from the pilot's own broker captures, before any judged run:

```
python scripts/general_method.py calibrate --runs <pilot runs folder> [--runs ...] \
    --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 \
    --out docs/results/general_method/allowance.json
python scripts/general_method.py read --runs <runs folder> [--runs ...] \
    --driver 10.2.1.10 --broker 10.2.1.21 --receiver 10.2.1.11 \
    --allowance docs/results/general_method/allowance.json \
    --out-runs docs/results/general_method/g_runs.csv
python scripts/general_method.py judge --runs-table docs/results/general_method/g_runs.csv \
    --out docs/results/general_method/g_verdicts.json
```

The pilot's runs are read with `--pilot` and never judged.

## The record

Registered on 23 October 2026. The pilot has not run yet.
