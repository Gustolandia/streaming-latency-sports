# R1: the receiving thread's own wait, measured three ways

A latency timed from the send, D = t_recv - t_send, cancels the wait of the thread that stamps the
broker's confirmation, because that wait lengthens one part of D exactly as much as it shortens
the other. It does not cancel the wait of the thread that stamps the receipt. The consumer reads
its clock only after its thread has been woken and given a CPU, so every D carries that wait,
always positive, where no check of the sign can see it. R1 measured that wait three ways in the
same runs on 3 October 2026, by a plan written before any run ([`r1_plan.md`](r1_plan.md)). R1 is
exploratory: it is not part of the registered law campaign, and what it found is a measurement
made after that campaign's verdicts.

*Words in this part.* **D**: a message's latency, timed from its send to its receipt on one clock.
**Stamp**: the moment a program reads the clock to record an event. **CPU**: one of the machine's
processors; a thread that is ready to run waits for one while all are busy.

## The three methods

1. **Go-first for the consumer alone.** The consumer, and nothing else, runs in the scheduler's
   real-time class, so its thread runs the moment it is woken. The fall in D at unchanged load is
   what that priority removes.
2. **The traced wait.** In a random half of the runs the scheduler's events were recorded, and the
   receiving thread's wait for a CPU before each stamp is read from them.
3. **The kernel's receive time.** In every run the receiver's packets were captured with the
   kernel's own timestamps. A message's delay from the packet that carries it to its stamp holds
   the wake-up, the wait for a CPU and the client's own work.

*Words in this part.* **Real-time class** (SCHED_FIFO, priority 80 here): its threads run before
every ordinary thread. **Traced run**: one whose scheduling events were recorded; the recording
costs time of its own. **Kernel**: the part of the operating system that takes packets off the
network and wakes the program waiting for them.

## The files

| File | What it is | Written by |
|---|---|---|
| [`r1_plan.md`](r1_plan.md) | the question, the methods, the design and four predictions, written before any run, and amendment R1-1 | hand |
| [`r1_design.json`](r1_design.json) | the eight setups and the seed their queue was shuffled with | hand |
| [`r1_registry_runs.csv`](r1_registry_runs.csv) | every R1 run, the two smoke runs included: machine, kernel, settings and verdict, in the main registry's columns ([`../registry/README.md`](../registry/README.md)) and two more, `consumer_priority` and `recv_capture` | `run_registry.py` |
| [`r1_runs.csv`](r1_runs.csv) | the three measurements for each run that counted, with its longest D, how many messages it held past the pause limit, and its disk wait | `recv_wait.py read` |
| [`r1_comparison.txt`](r1_comparison.txt) | the methods compared on each broker at each load, traced and untraced runs also shown apart, the runs that hold a pause named, and each prediction's verdict | `recv_wait.py compare` |
| [`r1_pauses.csv`](r1_pauses.csv) | every pause, read with the 28 September pause census's own functions | `recv_wait.py pauses` |
| [`a9_traced_receive_waits.csv`](a9_traced_receive_waits.csv) | method 2 on the law campaign's traced runs (A9), which the plan cites | `recv_wait.py traced` |
| [`a7_priority_delivery.csv`](a7_priority_delivery.csv) | D with and without go-first for both processes that read the clock (A7), which the plan cites | `recv_wait.py priority` |

From the repository's root, with the runs at home:

```
python scripts/run_registry.py --runs runs/azure/collected/matched/r1_smoke/runs --runs runs/azure/collected/matched/r1/runs --runs runs/azure/collected/matched/r1_more/runs --out docs/results/recv_wait/r1_registry_runs.csv
python scripts/recv_wait.py read --runs runs/azure/collected/matched/r1/runs --runs runs/azure/collected/matched/r1_more/runs --broker 10.1.1.21 --receiver 10.1.1.11 --out docs/results/recv_wait/r1_runs.csv
python scripts/recv_wait.py compare --table docs/results/recv_wait/r1_runs.csv --out docs/results/recv_wait/r1_comparison.txt
python scripts/recv_wait.py pauses --runs runs/azure/collected/matched/r1/runs --runs runs/azure/collected/matched/r1_more/runs --out docs/results/recv_wait/r1_pauses.csv
python scripts/recv_wait.py traced $(for f in runs/azure/final_campaigns/*/a9_*; do echo --runs $f; done) --out docs/results/recv_wait/a9_traced_receive_waits.csv
python scripts/recv_wait.py priority $(for f in runs/azure/final_campaigns/*/a7_*; do echo --runs $f; done) --out docs/results/recv_wait/a7_priority_delivery.csv
```

*Words in this part.* **Smoke run**: a short run made only to see that everything starts, records
and stops. **Pause limit**: the quality report's 150 ms; a message held longer marks a pause.
**Disk wait** (iowait): processor time spent idle while a task waited on the disk.

## The runs

53 runs on the first x86 pair, every one on kernel 6.8.0-1065-azure with 8 CPUs online and the
3 ms slice the plan set. Two smoke runs of 45 s came first, in queue `r1_smoke`. The integrity
rule sent both back, as it must at that length: 716 messages were sent after the warm-up against
the 750 planned, under its 99% floor. Their put-back attempts were never run. Then the 48 runs of
queue `r1`, eight setups in six shuffled rounds, and the 3 runs of queue `r1_more`, which
amendment R1-1 added so that every setup has at least three traced runs. All 51 counted.

The runs themselves are kept outside git, in `runs/azure/collected/matched/r1_smoke`, `r1` and
`r1_more`, each with the SHA256 manifest its files were checked against when they came home. The
pair was deallocated once they were home.

*Words in this part.* **Integrity rule**: `scripts/run_integrity.py`, which judges each run the
moment it ends: count it, run it again, or stop. **Warm-up**: the first 30 s of a run, left out
of every reading. **Slice**: how long the scheduler lets a thread run before it may switch.

## What the reading found

Each method's estimate of how much the receiving thread's wait adds to the mean of D, in
milliseconds: method 1 is the fall in mean D when the consumer alone goes first, and methods 2 and
3 the fall, between the same two arms, in the mean traced wait and in the mean delay from the
kernel's receive time to the stamp.

| Broker, load | Method 1 | Method 2 | Method 3 | Largest over smallest |
|---|---|---|---|---|
| Kafka, 75% | 0.43 | 0.70 | 0.64 | 1.64 |
| Kafka, 88% | 0.94 | 0.91 | 0.92 | 1.04 |
| Redis, 75% | 0.47 | 0.50 | 0.47 | 1.07 |
| Redis, 88% | 0.43 | 0.62 | 0.41 | 1.49 |

Each prediction was stated for both brokers at both loads. Read that way, R1-a holds and R1-b,
R1-c and R1-d do not.

- **R1-a holds.** In ordinary runs the traced wait's mean lies between 0.3 and 1.2 ms and its 90th
  percentile above 1.5 ms, on both brokers at both loads; under go-first its mean is below 0.1 ms.
- **R1-b fails on Kafka.** Go-first for the consumer lowers the 90th percentile of D on Redis by
  2.14 ms at 75% load and 1.96 ms at 88%, and moves its median by 0.05 ms at both. On Kafka the
  90th percentile falls 0.95 ms at 75%, short of the plan's 1 ms, and at 88% the median moves
  0.60 ms, past the plan's 0.3 ms.
- **R1-c fails on Kafka.** In every one of the 27 traced runs more than 99.7% of messages have a
  kernel delay at least as long as their traced wait. The median of the difference, the client's own work after
  its thread runs, is 0.11 and 0.12 ms on Redis but 0.37 and 0.39 ms on Kafka, past the plan's
  0.3 ms.
- **R1-d fails at one point.** At 75% load on Kafka method 1 gives 0.43 ms against method 2's
  0.70.

*Words in this part.* **Arm**: one side of the comparison, ordinary or go-first. **90th
percentile**: the value nine messages in ten stay under. **Median over runs**: a setup's value is
the median of its runs' values, so one odd run does not move it.

## Two things found on the way

**Pauses.** Five of the 51 runs hold a message past the pause limit. A pause releases every
message it held at once, so one pause can carry a run's mean. The three on Redis, all in
go-first runs, last 0.79, 1.73 and 6.04 s, and they look like the driver's own stalls read on 28
September ([`../law/the-strange-results-read-28-sep.md`](../law/the-strange-results-read-28-sep.md)):
the broker's confirmations stayed under 4 ms, the separate sampler on the driver stopped as well
(for 1.45, 2.15 and 7.10 s), and the consumer spent under 0.2% of each pause inside a read. Their
runs waited 2.42, 11.56 and 9.34 s on the disk, in the same order, against a median of 0.08 s over
all 51 runs; but an ordinary Redis run waited 41.18 s on the disk and held nothing, so a disk wait
alone does not make a pause. The other two are on Kafka: a receiving-side pause of 3.71 s in an ordinary run at
88%, during which the sampler kept going, and a broker-side one of 0.17 s. A setup's value, a
median over its runs, sets the pauses aside. A cell of two runs cannot, which is why the two
untraced go-first Redis runs at 75% show a mean D of 93.22 ms. The comparison names the runs that
hold a pause beside each part.

**A stop that killed its own sudo.** `pkill -f` matches whole command lines and leaves out only
itself, and the sudo that runs it holds the pattern in its own command line. So the forced stop of
the receiver's capture killed its own sudo in every one of the 53 runs, and each run's log said
so. No data was lost: the interrupt before it had already ended the capture, and no message is
missing from any capture. `campaign.sh` now writes the pattern as `[t]cpdump`, which still matches
tcpdump and no longer matches itself, for R1's capture and M0's.

*Words in this part.* **Sampler**: `util_sampler.py`, a separate process that writes a line every
half second; a gap in its lines means the whole machine stopped, not one program. **Broker-side**
and **receiving-side**: whether the broker's confirmations were held as long as the deliveries, or
only the deliveries were. **sudo**: the command that runs another as the administrator.

## Pocket dictionary

- **Arm**: one side of the comparison, ordinary or go-first.
- **Broker**: the server that carries messages between programs; here Kafka or Redis.
- **CPU**: one of the machine's processors.
- **D**: a message's latency, timed from its send to its receipt on one clock.
- **Disk wait** (iowait): processor time spent idle while a task waited on the disk.
- **Go-first**: the scheduler's real-time class, SCHED_FIFO at priority 80.
- **Integrity rule**: the check that decides, as each run ends, whether it counts.
- **Kernel**: the part of the operating system that takes packets off the network.
- **Median over runs**: a setup's value, which one odd run does not move.
- **Pause**: a message held past the quality report's 150 ms limit.
- **Sampler**: a separate process on the driver that writes a line every half second.
- **Stamp**: the moment a program reads the clock to record an event.
- **Traced run**: a run whose scheduling events were recorded.
