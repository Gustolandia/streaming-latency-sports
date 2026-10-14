# F2: the full fix, as a benchmark tool would read it

F1 ([`../full_fix`](../full_fix/README.md)) showed that a latency timed between the kernel's own
timestamps, as a message leaves the client machine and as it returns, held still across background
load and priority, while the latency timed from the publish call rose in its tail. F1 read those
timestamps from packet captures. A benchmark tool would not run a capture: it would ask the kernel
for the same timestamps on its own sockets, through the `SO_TIMESTAMPING` socket option. The block
F2 tests that form, with the captures running beside it as the reference. Its plan is frozen in
[`freezes/40-experiment-plan`](../../../freezes/40-experiment-plan/) (plan version 43), and its
predictions were written, and fingerprinted, before any of its runs, the pilot included.

*Words in this part.* **Socket**: the end of a network connection a program reads and writes.
**Socket option**: a setting a program asks the kernel for on one of its sockets.
**`SO_TIMESTAMPING`**: the Linux socket option that hands a program the kernel's own timestamps of
the packets it sends and receives.

## What is measured

Each message carries the four times F1 recorded, and two more, all on the driver's one clock:

| Time | Where it is taken |
|---|---|
| `t_tx_so` | the kernel's transmit timestamp of the producer's send call that carried the end of the message's id, read by the producer from its socket's error queue (`producer_so.csv`) |
| `t_rx_so` | the kernel's receive timestamp returned with the consumer's read that delivered the end of the message's id (`consumer_so.csv`) |

From them `W_so = t_rx_so - t_tx_so`, beside F1's `W = t_rx - t_tx` from the captures.

The clients read the timestamps through a small module, [`scripts/so_timestamps.py`](../../../scripts/so_timestamps.py),
which replaces the socket class in each client's process before the client library opens its
connections. On each connection to the broker's port it turns the option on at the first send or
read, once the connection is up, so that byte offsets count from the first byte sent. Each
transmit timestamp carries the byte offset of its send call's last byte, so a message is matched
to the first timestamp at or after its id's last byte. The module drains the error queue only when
`poll()` reports something waiting, and finds each event id in the bytes as `scripts/full_fix.py`
finds it in the captures. The client libraries, kafka-python and redis-py, are unchanged.

*Words in this part.* **Error queue**: where the kernel leaves a socket's transmit timestamps for
the program to collect. **Byte offset**: how many bytes the connection had carried before a given
byte.

## The predictions

Fixed in [`DESIGN.md`](DESIGN.md) before any run, its fingerprint recorded in
[`DESIGN_TIMESTAMP_NOTE.md`](DESIGN_TIMESTAMP_NOTE.md). A setup's value is the median over its
passing runs of each run's statistic.

- **G-a.** The socket option agrees with the captures: in every setup the median of `|W_so - W|`
  is at most 20 µs, and its 99th percentile at most 100 µs.
- **G-b.** `W_so`'s median moves by less than 10% between idle and 88% load, and between normal and
  real-time priority, on both brokers.
- **G-c.** The same for `W_so`'s 99th percentile, within 25%.
- **G-d.** No message has `W_so` at or below zero, and either socket misses under 0.5% of a run's
  messages.
- **G-e.** In the same runs, at normal priority, `D`'s 99th percentile at 88% load is at least 1.5
  times its value idle, and `W_so`'s mean moves by less than a fifth of the rise in `D`'s mean.

*Words in this part.* **Median**: the middle value. **99th percentile**: the value 99% of messages
stay below. **Setup**: one combination of broker, load and priority.

## The pilot

Two steps on 14 October, after the predictions and before any judged run; they could change
instruments only. The first step ran one idle run on each broker. On Redis the run passed the
integrity rule and every message got a receive timestamp, but the producer got no transmit
timestamp at all. Probes on the driver ([`code/`](code/), their output in [`probes/`](probes/))
showed why: the kernel gives software transmit timestamps on the loopback device but none on the
path to the broker, while the timestamp taken as a packet enters the device queue arrives for every
send, twice; the first is kept. So, as the design said it would, the transmit timestamp is taken at
the queue (`--so-transmit sched`). On Kafka all three attempts failed before a message was sent:
kafka-python sets a timeout on its socket while it sends, and on such a socket Python waits for the
socket to become readable before it reads the error queue, so the module held each request past the
client's own timeout. The module now drains the queue only when `poll()` reports something waiting.

The second step ran all eight setups with both changes, and every check in
[`f2_pilot_runs.csv`](f2_pilot_runs.csv) came out clean: every run passed the integrity rule, no
capture dropped a packet, each of the 4,988 messages per run was found in both captures and had both
socket timestamps, and no socket latency came out at or below zero.

*Words in this part.* **Pilot**: a short run of a block to check its instruments, never judged.
**Device queue**: where the kernel holds a packet before the network driver takes it.

## The files

| File | What it holds | Made by |
|---|---|---|
| [`DESIGN.md`](DESIGN.md) | the claim, the design, the predictions and their margins, written before any F2 run | by hand |
| [`DESIGN_TIMESTAMP_NOTE.md`](DESIGN_TIMESTAMP_NOTE.md) | DESIGN.md's fingerprint and when it was recorded | by hand |
| [`f2_design.json`](f2_design.json) | the judged block: eight setups, six rounds, its seed | by hand |
| [`f2_smoke_design.json`](f2_smoke_design.json), [`f2_pilot_design.json`](f2_pilot_design.json) | the pilot's two steps | by hand |
| [`f2_pilot_runs.csv`](f2_pilot_runs.csv) | each pilot run's checks and spans | `scripts/so_fix.py read` |
| [`code/`](code/), [`probes/`](probes/) | the three probes run on the driver, and what each printed | by hand, run on the driver |

The pilot's runs are in `runs/azure/collected/matched/f2_smoke` and `f2_pilot`, and the probes and
both steps' logs, with the runner and the clients as the pilot ran them, in
`snapshot_20261013T234847Z`, each with its fingerprints.

## How to reproduce

```bash
python3 scripts/run_queue.py make --design docs/results/so_fix/f2_design.json --out runs/azure/queues/f2.csv
bash cloud/azure/campaign.sh runs/azure/queues/f2.csv
python scripts/so_fix.py read --runs runs/azure/collected/matched/f2/runs --driver 10.1.1.10 --broker 10.1.1.21 --receiver 10.1.1.11 --out docs/results/so_fix/f2_runs.csv
python scripts/so_fix.py judge --table docs/results/so_fix/f2_runs.csv --out docs/results/so_fix/f2_verdicts.json
```

The first two lines run on the first x86 pair's driver; its own work list runs them.

## Pocket dictionary

| Word | Meaning |
|---|---|
| Byte offset | how many bytes a connection had carried before a given byte |
| D | the latency from the publish call to the consumer's timestamp |
| Device queue | where the kernel holds a packet before the network driver takes it |
| Error queue | where the kernel leaves a socket's transmit timestamps for the program to collect |
| Pilot | a short, unjudged run of a block, to check its instruments |
| Socket | the end of a network connection a program reads and writes |
| `SO_TIMESTAMPING` | the Linux socket option that hands a program the kernel's timestamps of its packets |
| W | the kernel-timed latency read from the captures |
| W_so | the same latency read by the clients on their own sockets |
