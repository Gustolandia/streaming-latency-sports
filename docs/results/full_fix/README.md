# F1: a full fix, tested

Every remedy the paper names leaves something behind. Timing from the publish call cancels the
wait of the thread that reads the broker's confirmation, but keeps the wait of the thread that
stamps the receipt. Real-time priority shortens the waits without ending them. The block F1 tests
a fix that leaves nothing: both of a message's timestamps taken in the client machine's kernel,
where the message leaves and where it arrives, so that no program thread's wait for a core can
enter the latency a benchmark reports. Its plan is frozen in
[`freezes/39-experiment-plan`](../../../freezes/39-experiment-plan/) (plan version 42), and its
predictions were written, and fingerprinted, before any of its runs, the pilot included.

*Words in this part.* **Kernel**: the part of the operating system that sends and receives
packets; it stamps each packet with the time as it passes, whether or not any program is running.
**Wait for a core**: the time a thread that is ready to run spends waiting for a processor while
every one is busy. **Freeze**: a plan committed before the runs it covers.

## What is measured

Each run records four times for every message, all on the driver's one clock:

| Time | Where it is taken |
|---|---|
| `t_pub` | the producer's clock at the publish call (`producer.csv`) |
| `t_tx` | the kernel's timestamp of the packet that carried the end of the message's id out of the driver, captured on the driver's own interface (`sender_full.pcap`, new in F1) |
| `t_rx` | the same for the packet that brought it in, captured in the receiver's namespace (`receiver_full.pcap`, as R1 captured it) |
| `t_recv` | the consumer's clock when it stamps the message (`consumer_events.csv`) |

From them come four spans, with `D = H_send + W + H_recv` for every message:

- `D = t_recv - t_pub`, what a benchmark timed from the publish call reports;
- `W = t_rx - t_tx`, the wire time, network and broker: the fix;
- `H_send = t_tx - t_pub`, the host's wait before the bytes leave;
- `H_recv = t_recv - t_rx`, the host's wait after they arrive.

The receiver's packets are also captured as the network card itself stamped them, on its own
clock (`receiver_hw.pcap`), with that clock sampled against the system's twice a second
(`phc_offset.csv`, by [`scripts/phc_offset.py`](../../../scripts/phc_offset.py)). The card stamps a
packet before the kernel does, so the kernel's stamp less the card's is the kernel's own delay,
the one part of the host a kernel timestamp keeps. It is described and not judged. (The plan's
D42-2 words this the other way round, as the card's arrival less the kernel's; the delay is the
kernel's less the card's, as `scripts/full_fix.py` computes it.)

*Words in this part.* **Capture**: a recording of the packets that pass an interface, each with
its timestamp. **Namespace**: a separate copy of the machine's network settings; the receiver
runs in its own, as in every law campaign. **Wire time**: here, everything between the two
kernel stamps: the network both ways and the broker.

## The predictions

Fixed in [`DESIGN.md`](DESIGN.md) before any run, its fingerprint recorded in
[`DESIGN_TIMESTAMP_NOTE.md`](DESIGN_TIMESTAMP_NOTE.md). A setup's value is the median over its
passing runs of each run's statistic.

- **F-a.** `W`'s median moves by less than 10% between idle and 88% load, and between normal and
  real-time priority, on both brokers.
- **F-b.** The same for `W`'s 99th percentile, within 25%.
- **F-c.** No message has `W` at or below zero, and either capture misses under 0.5% of a run's
  messages.
- **F-d.** In the same runs, at normal priority, `D`'s 99th percentile at 88% load is at least 1.5
  times its value idle, and `W`'s mean moves by less than a fifth of the rise in `D`'s mean: the
  effect is present, and it is the host's.
- **F-e.** On Kafka at 88% load and normal priority, `H_send`'s mean is at least 0.2 ms larger than
  idle; on Redis it moves by less than 0.1 ms.

Pauses are marked as R1 marked them, by the quality report's limit of 150 ms, in `D` and in `W`,
and the runs they held are listed beside the verdicts.

*Words in this part.* **Median**: the middle value. **99th percentile**: the value 99% of
messages stay below. **Setup**: one combination of broker, load and priority.

## The pilot

One round of the eight setups, on 13 October, after the predictions and before any judged run;
it could change instruments only. Its first attempt stopped at its first idle run, because the
runner treats an unset variable as an error and an idle run, which starts no load, left one
unset. In the same attempt the card's capture found no device, because it read the wrong column
of the link listing. Both are fixed in `cloud/azure/campaign.sh`, each with a test in
`tests/unit/test_azure_kit.py` that fails on the old line. The second attempt ran all eight
setups, and every check in [`f1_pilot_runs.csv`](f1_pilot_runs.csv) came out clean: every run
passed the integrity rule, no capture dropped a packet, every message was found in both captures,
no wire time was at or below zero, and the card stamped every packet after it left the driver and
before the kernel stamped it. Since the card offers its own receive timestamps, as the design
said it might, every run of the block captures them (`hw_capture` in
[`f1_design.json`](f1_design.json)).

The design note named the broker's port in the sender's capture filter; the capture as run
leaves out the driver's ssh traffic instead, since one runner serves both brokers on their own
ports. It is the same set of packets: the producer's, from the driver to the broker.

*Words in this part.* **Pilot**: a short run of a block to check its instruments, never judged.
**Integrity rule**: the checks every run must pass before it is read (`scripts/run_integrity.py`).

## The result

The 48 runs ran on 13 October 2026, from 15:58 to 18:17 UTC, and every one passed the integrity
rule at its first attempt. All five predictions held ([`f1_verdicts.json`](f1_verdicts.json),
written by `scripts/full_fix.py judge` from [`f1_runs.csv`](f1_runs.csv)):

- **F-a held.** The wire time's median moved by at most 7.9%, against the 10% allowed. The largest
  move was a fall under load, on Redis at real-time priority, from 639 to 588 µs.
- **F-b held.** Its 99th percentile moved by at most 7.2%, against 25%.
- **F-c held.** None of the 239,424 messages had a wire time at or below zero, both captures found
  every message, and no capture dropped a packet.
- **F-d held.** At normal priority the load raised `D`'s 99th percentile 4.6-fold on Kafka, from
  1,801 to 8,299 µs, and 4.3-fold on Redis, from 1,011 to 4,396 µs, while `W`'s mean moved by
  0.2% and 5.1% of the rise in `D`'s mean.
- **F-e held.** Kafka's wait before its bytes leave rose 626 µs on the mean, from 573 to 1,199 µs;
  Redis's moved 4 µs, from 92 to 88 µs.

No message arrived more than 150 ms late, so no pause is marked. Described and not judged, the
kernel stamped each packet 6 to 20 µs after the card did, the medians of the eight setups, longest
on an idle machine. Of the 50 µs by which the wire time's median fell on Redis at real-time
priority, 30 µs lay before the card, between the kernel's departure stamp and the card's arrival
stamp.

*Words in this part.* **Held**: the measured values stayed inside the margins the prediction set
before the runs. **Fold**: how many times larger.

## The files

| File | What it holds | Made by |
|---|---|---|
| [`DESIGN.md`](DESIGN.md) | the claim, the design, the predictions and their margins, written before any F1 run | by hand |
| [`DESIGN_TIMESTAMP_NOTE.md`](DESIGN_TIMESTAMP_NOTE.md) | DESIGN.md's fingerprint and when it was recorded | by hand |
| [`f1_design.json`](f1_design.json) | the judged block: eight setups, six rounds, its seed | by hand |
| [`f1_pilot_design.json`](f1_pilot_design.json), [`f1_pilot2_design.json`](f1_pilot2_design.json) | the pilot's two attempts | by hand |
| [`f1_pilot_runs.csv`](f1_pilot_runs.csv) | each passing pilot run's checks and spans | `scripts/full_fix.py read` |
| [`f1_runs.csv`](f1_runs.csv) | each of the 48 judged runs' checks and spans | `scripts/full_fix.py read` |
| [`f1_verdicts.json`](f1_verdicts.json) | F-a to F-e and the values behind each, with the runs a pause held | `scripts/full_fix.py judge` |
| [`f1_registry_runs.csv`](f1_registry_runs.csv) | every F1 run, the pilots' included: machine, kernel, settings and verdict, in the main registry's columns | `scripts/run_registry.py` |
| [`r1_kernel_vs_app.csv`](r1_kernel_vs_app.csv) | the reading of R1's runs that prompted F1, exploratory | [`code/explore_r1.py`](code/explore_r1.py) |

The pilot's runs are in `runs/azure/collected/matched/f1_pilot`, `f1_pilot2` and
`snapshot_20261013T124310Z` (the stopped run, both attempts' logs, and the runner and sampler as
the pilot ran them), each with its fingerprints. The 48 judged runs are in
`runs/azure/collected/matched/f1`, and the pair's work list logs and its own register of every run
in `snapshot_20261013T182020Z`. The register lists the stopped pilot run with no verdict, and
names every run's card capture as asked for; in the first pilot's runs it found no device.

## How to reproduce

```bash
python3 scripts/run_queue.py make --design docs/results/full_fix/f1_design.json --out runs/azure/queues/f1.csv
bash cloud/azure/campaign.sh runs/azure/queues/f1.csv
python scripts/full_fix.py read --runs runs/azure/collected/matched/f1/runs --driver 10.1.1.10 --broker 10.1.1.21 --receiver 10.1.1.11 --out docs/results/full_fix/f1_runs.csv
python scripts/full_fix.py judge --table docs/results/full_fix/f1_runs.csv --out docs/results/full_fix/f1_verdicts.json
python scripts/run_registry.py --runs runs/azure/collected/matched/f1_pilot/runs --runs runs/azure/collected/matched/f1_pilot2/runs --runs runs/azure/collected/matched/snapshot_20261013T124310Z/runs --runs runs/azure/collected/matched/f1/runs --out docs/results/full_fix/f1_registry_runs.csv
```

The first two lines run on the first x86 pair's driver; its own work list runs them.

## Pocket dictionary

| Word | Meaning |
|---|---|
| Capture | a recording of packets with their timestamps |
| D | the latency from the publish call to the consumer's stamp |
| Fold | how many times larger |
| Freeze | a plan committed before its runs |
| H_send, H_recv | the host's waits before the bytes leave and after they arrive |
| Held | stayed inside the margins a prediction set before the runs |
| Kernel | the part of the operating system that sends and receives packets |
| Network card's clock | the card's own clock, which stamps a packet before the kernel sees it |
| Pilot | a short, unjudged run of a block, to check its instruments |
| Setup | one combination of broker, load and priority |
| W | the wire time, from the kernel's stamp as a message leaves to its stamp as it arrives |
