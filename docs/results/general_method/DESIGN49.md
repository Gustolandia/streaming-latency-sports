# Freeze 46 (plan version 49): the remedy by protocol, judged by what it changes

Written 25 October 2026, after version 47's verdicts (`9e6c422c`, [`README.md`](README.md), "The
verdicts") and before any run this version covers. Versions 47 and 48 ([`DESIGN47.md`](DESIGN47.md),
[`DESIGN48.md`](DESIGN48.md)) stand, with their verdicts. This version adds new blocks on new runs.
It changes no earlier prediction and no earlier verdict.

**What prompted it.** Version 47 confirmed the method's measurement and its check:
- the client host's per-packet timestamps, matched by the broker's ids (M1-b);
- the check's certain reading (M2-a), its estimate (M2-b), and the clients' own certification that a
  request was waiting (M2-c on Redis and NATS).

It did not confirm the remedy as it was registered. Read after the verdicts, three of the remedy's
failures came from what the predictions read, not from the remedy:
- **V-a and N-a.** Where requests waited, `W`'s tail held still: ratios 0.98 to 1.03, equivalence p
  at most 0.003. But the predictions also asked that the load reach the application, and they read
  that as `D`'s on/off ratio over `W`'s top 1%. Where the remedy works, those are the messages
  slowest in the network, not the ones the load slows in the application. `D` grew there only 1.14
  to 1.47 times, where 1.5 was asked. Over `D`'s own top 1%, `D` grew 3.1 to 6.5 times in the same
  runs of the setups this version repeats.
- **KC-d.** With librdkafka's broker thread at real-time priority, `W`'s tail fell in the on-blocks
  in two runs (ratios 0.31 and 0.33). In those runs `F`'s off-block tail, the broker's and the
  network's side, was 4.4 to 4.7 ms, against 1.4 to 1.5 ms in the on-blocks. `W` carries `F`, so `W`
  cannot show what the thread's priority changes. The client's own part of the latency (below) rose
  by 4 to 16 µs in those runs, against 2.8 to 3.4 ms at normal priority.
- **The Arm pair's KC-d.** The Arm pair's broker stalled, for up to 210 ms, and `W`'s tail ratios
  followed the stalls.

The fourth was the bound:
- **P-a was not judged.** RabbitMQ's checks of `B` failed in all four runs. The client captures fell
  silent for 13 to 20 ms, longer than `B` = 10 ms.

This version tests the remedy again, on new runs, by what the remedy changes:
- **On Redis and Kafka, within one block, against the same load.** The setup with the problem and
  the setup with the remedy run in the same block, in random order.
- **On Kafka, by the client's own part of the latency.** A delay on the broker's side can raise it
  only up to the client's own turnaround.
- **By a load check read where the load acts:** `D`'s own top 1%.
- **On RabbitMQ, with a bound `B` wider than its pauses.**

**On NATS and RabbitMQ it shows less.** In version 47, NATS at depth 1 and RabbitMQ at a prefetch of
1 fell behind 2,000 messages a second, so the load could not open a gap that the remedy would then
remove (M3-b). Their blocks therefore judge only that, where requests or credit wait, `W` holds
still while the load reaches the application. They do not judge how much of a gap the remedy
removes.

These predictions were chosen after reading version 47's runs of the same setups, and every one of
them holds on those runs (D49-9). The new runs are their only test.

A draft of this version was read against the code and version 47's runs before it was frozen. That
reading changed it in five places:
- NATS and RabbitMQ are judged only where requests or credit wait;
- every own tail is taken by count;
- a rise is judged by its size, whatever its sign;
- each run's instrument is checked;
- the parts of `W` are described by load state.

*Words in this part.*
- **The client's part:** `W − F` for each message. On Kafka it is `min(T_c, S)`, the time the
  message waited at the broker because this client had not yet asked again. `T_c`, the client's
  turnaround, is timed on the client host, from the previous answer's last byte to the next request,
  so a delay on the broker's side can raise the client's part only up to `T_c`. On Redis, NATS and
  RabbitMQ it is `S`, the time the message was stored at the broker before its request came,
  whatever kept the request; there it is described, not judged.
- **Own tail:** a quantity's mean over its own top 1% in a load state: the largest values of 1% of
  the state's messages, by count, at least one. It is taken instead of the mean over `W`'s top 1%.
- **The load check:** the clause that shows the load reached the client, so that a remedy that holds
  `W` still is tested against a load that did something.
- **Bound `B`:** the largest one-way crossing or timing error the certification allows. The run's
  own checks of `B` say whether its run stayed within it.

## What is measured, beyond version 47 (D49-1)

Every run is read by `scripts/general_method.py`'s `read_run`, as in version 47. It now also gives:
- **The client's part, `W − F`,** for each message, from the broker's capture (`WF`). The same from
  the clients' timestamps alone, `W − Fc` (`WFc`), is described beside it. For each, `read_run`
  gives:
  - the tail mean over `W`'s top 1% in each load state;
  - the own tail in each state;
  - their on/off ratios and rises.
- **The rise of each own tail,** the on-blocks' less the off-blocks'. Before, only the ratio was
  given. Every own tail is now taken by count, as defined above.
- **The parts of `W` the load could move the other way,** each by its own tail in each load state:
  - the card's lag `Q`, packet by packet: the kernel's receive timestamp less the card's;
  - the broker's residence, message by message: the last byte of its answer leaving the broker less
    the last byte of the request that carried it arriving there (`R_out − P_in`).
- **The share of the time the consumer's thread waited for a core** in each load state, from the
  consumer's own samples of its thread (`consumer_schedstat.csv`). It shows the load reaching the
  client, and `W` cannot change it. nats.go takes no samples.
- **The certification and its checks at `B` = 50 ms** (`certified_share_50ms`, `b_checks_50ms`),
  beside 10 ms and 2 ms.

The rest of each row is unchanged, and version 47's judge reads none of these fields.

## The blocks (D49-2 to D49-6)

Blocks R, J, G and Q run on the second x86 pair, in that order, and block Z on the Arm pair, at the
same time. Every run is as version 47's:
- 2,000 messages a second, Poisson sends, 70 s with a 20-s warm-up;
- the load at 70%, switched on and off in 5-s blocks, at the duty version 47's pilot froze for the
  setup;
- the producer at real-time priority, and the clients' collectors off;
- every capture version 47 took, the run's facts, and the brokers' images pinned;
- each campaign primed on its brokers;
- version 46's integrity rule with its lateness rule. A run that fails it is repeated by the queue,
  and the failed attempt is kept.

Each setup is version 47's judged setup with the same settings and duty, under a new id
(`g49{r,j,g,q,z}_design.json`).

| Block | Pair | Setups | Runs |
|---|---|---|---|
| R | x86 | Redis's waiting consumer at depth 1 (the gap) and at depth 256 with one reply per read (the remedy) | 12 |
| J | x86 | NATS: our pull consumer at depth 256, and nats.go's `Consume()` | 12 |
| G | x86 | RabbitMQ at a prefetch of 1,000 | 6 |
| Q | x86 | librdkafka at normal priority (the gap), and with only its broker thread at real-time priority (the remedy) | 12 |
| Z | Arm | block Q's two setups | 12 |

Six rounds of each setup, as the rounds rule asks (D49-7), in random order within each round, from
seed 20261104. That makes 42 runs on the x86 pair and 12 on the Arm pair. Block G's one setup has no
order to shuffle. Its queue is six one-round queues, made by `scripts/run_queue.py` from its design
with the first round set to 1 to 6, and joined in that order.

## Predictions

A cell is one setup, or one comparison of two setups, in one block. A prediction holds where every
cell it reaches holds. A cell missing a value it needs is out of reach, reported and not judged. A
cell that rests on another cell that did not hold is not judged. A setup's value is the median over
its judged runs.

**The runs judged.**
- Each block is judged on the runs of its own pair.
- A run whose own instrument does not check out is left out, as a run that fails its integrity rule
  is, and listed. Its instrument checks out where:
  - the broker's ids pair every message the payload's ids pair, and none differently, the confirm
    and delivery orders agreeing on RabbitMQ (version 47's M1-b);
  - the certain reading calls no message unwaited that the broker shows waiting (M2-a).
- A setup with no judged run gives each prediction that reaches it a cell out of reach.

### Redis: the gap and the remedy in one block (R)

- **R-a, the gap.** At depth 1, `W`'s tail on/off ratio is at least 1.5.
- **R-b, requests waiting.** At depth 256, as M2-c reads it:
  - the broker's record shows a request waiting for at least 99.9% of messages;
  - the clients' own timestamps certify one, at `B` = 10 ms, for at least 99.9% of them, the share
    taken over the runs whose checks of `B` hold.
- **R-c, `W` held still.** Where R-b holds, at depth 256:
  - `W`'s tail, over all messages, is held still: its on/off ratio lies within 1/1.2 and 1.2 by two
    one-sided tests across the runs at α = 0.05;
  - while `D`'s own tail on/off ratio is at least 1.5, which shows that the load reached the
    application.

  Version 47 read `W` over the messages that found a request waiting; reading it over all messages
  is stricter. It read the load check over `W`'s top 1%, and on version 47's own runs that reading
  would fail here: 1.46 at depth 256 against the 1.5 asked. It is described beside R-c, with the
  parts of `W` (D49-1).
- **R-d, the remedy's size.** Where R-a and R-b hold, the rise of `W`'s tail at depth 256 is at most
  a tenth of its rise at depth 1, in size: a fall counts as a rise. A run-level 95% interval of the
  ratio of the two rises is given beside it, from 2,000 draws, seed 20261104.

### NATS: requests waiting (J)

- **J-a.** As R-b, for our pull consumer at depth 256 and for nats.go's `Consume()`, at `B` = 10 ms.
- **J-b, `W` held still where requests wait.** As R-c, for each, where its J-a cell holds. On
  version 47's runs, the load check read over `W`'s top 1% would fail here too (1.27 and 1.14).

### RabbitMQ: credit waiting, certified at a wider bound (G)

- **G-a.** As R-b, at a prefetch of 1,000, with `B` = 50 ms. In version 47's runs at this prefetch,
  the client captures fell silent for 13.4 to 19.4 ms, so a bound of 10 ms could not be held. At 50
  ms the longest silence seen is still below two fifths of the bound. A larger `B` counts only the
  credit granted further before each message left, and the answers further after its acknowledgment
  came back, so it certifies fewer messages, never more. The same at 10 ms is described beside it.
  The wider bound is RabbitMQ's alone: at 50 ms, version 47's Redis runs at depth 256 certify only
  99.85 to 99.97% of messages.
- **G-b, `W` held still where credit waits.** As R-c, where G-a holds.

### Kafka: the client's part, with the problem and the remedy in one block (Q)

- **Q-a, the gap.** With librdkafka at normal priority, the client's part's own tail on/off ratio is
  at least 1.5.
- **Q-b, the remedy's size.** Where Q-a holds, with only librdkafka's broker thread at real-time
  priority, the rise of the client's part's own tail is, in size:
  - at most a tenth of its rise at normal priority;
  - and at most 50 µs, the check's resolution, below which the check calls no message unwaited.

  A run-level 95% interval of the first is given beside it, as for R-d. The client's part is at most
  the client's turnaround, so Q-b reads again, in what the latency carries, the turnaround whose
  tail ratio KC-h found at 1.09, within its 1.2.
- **Q-c, the round trip stays.** With only the broker thread at real-time priority, in both load
  states, at least half of the messages found no fetch waiting, by the broker's record. This is
  KC-h's second clause, read again. A fetch thread that does nothing else still waits a round trip
  for each answer, and a message that arrives meanwhile waits for the next fetch. That wait is the
  protocol's latency, and `F` keeps it.

Described beside them, setup by setup: `W`'s and `F`'s tails, ratios and rises, which carry the
broker's delays; `D`'s; the client's part from the clients' timestamps alone; and the gap at the
broker with its split.

### Kafka on the Arm pair (Z)

- **Z-a and Z-b:** Q-a and Q-b, on the Arm pair.
- **Q-c is described there, not judged.** In version 47's runs on this pair, with the broker thread
  raised, the gap at the broker from a fetch's answer to the next fetch was 69 to 75 µs, against 637
  to 727 µs on x86. A fetch was waiting for 98.0 to 99.7% of messages in each load state.

## The judging

The judge is `scripts/general_method49.py judge`. It reads the run tables that `general_method49.py
read` writes. Its margins are fixed in the code and pinned by the record's test:
- 1.5 for R-a, Q-a and Z-a, and for the load check in R-c, J-b and G-b;
- 1/1.2 to 1.2 and α = 0.05 for `W` held still;
- 99.9% for waiting and for certification;
- `B` = 10 ms for R-b and J-a, and 50 ms for G-a;
- a tenth for R-d, Q-b and Z-b, and 50 µs for Q-b and Z-b;
- one half for Q-c.

## The rounds (D49-7)

This version has no pilot. Every setup ran in version 47's judged blocks, with the duty, broker and
captures it runs with here, and with version 48's kit, which leaves these setups as version 47 ran
them. Those runs, read by this version's reader, are the values the rounds rule draws about. The
rule is version 45's, through this version's judge (`scripts/general_method49.py power`, 2,000
made-up blocks, seed 20261104).

**It asks for six rounds.** At four rounds the rule brings R-d to 0.769, and at five 0.768, short of
0.8. At six rounds, the share of made-up blocks that confirm each prediction is:

| | R-a | R-b | R-c | R-d | J-a | J-b | G-a | G-b | Q-a | Q-b | Q-c | Z-a | Z-b |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| The rule | 0.994 | 1.000 | 0.066 | 0.843 | 1.000 | 0.002 | 1.000 | 0.060 | 1.000 | 1.000 | 0.977 | 1.000 | 1.000 |
| The runs' own spread | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.977 | 1.000 | 1.000 |

- **No number of rounds up to twelve brings R-c, J-b or G-b to the bar.** These are the "held still"
  clauses. The rule draws the two load states of a run on their own, so each run's ratio gets the
  spread of two whole runs, though both states share the run's connections and path. With each ratio
  drawn at the spread version 47's own repeated runs show, these clauses reach 1.000, 1.000 and
  1.000 at six rounds. That spread is described and is not the rule. They are reported at the rounds
  the others need, as version 47 reported M3-a and KC-d.
- **With the load's excess halved,** R-a falls to 0.580 and R-d to 0.369 under the rule. Under the
  runs' own spread both are at 0.907.
- **One departure from the rule.** Whether a prediction clears its margin is judged on version 47's
  own runs, four of each setup. The rule judges each setup's means twice, which would take each
  run's checks of `B` from the setup's first run alone.
- **These numbers are optimistic.** They are drawn about the runs that chose the predictions.
- `g49_power.json` and `g49_power_pilot_spread.json` hold the numbers, and `g49_from47_runs.csv` the
  runs.

## How it is run and read (D49-8)

- **The code.** Both pairs run the checkout of this version's freeze. The run kit is version 48's,
  unchanged.
- **The reading.** Once a pair's list has run, each block is read on its own driver, by
  `general_method49.py read` with each pair's allowance from version 47's pilot
  (`allowance_x86.json`, `allowance_arm.json`).
- **The fingerprints.** Every file of every run, the failed attempts' among them, is fingerprinted
  there in a `SHA256SUMS`. The table and the fingerprints come home.
- **The runs.** They stay on the driver's disk, which is kept when the pair stops. They are copied
  home, and checked against those fingerprints, once the home machine has room: on 25 October 2026
  it had 13 GB free, against about 27 GB for this version's runs.
- **The judging** reads the tables only.

## What was read before this version (D49-9)

Version 47's 36 judged runs of the nine setups this version repeats were read again with this
version's reader. Their values:
- **Redis.** At depth 1, `W`'s tail ratio was 1.97 to 2.29, and its rise 1.71 to 1.85 ms. At depth
  256, the rise was −23 to +20 µs, a request waited for every message and every message was
  certified at 10 ms in every run, and `D`'s own tail ratio was 3.1 to 5.0.
- **NATS.** A request waited for every message, and every message was certified at 10 ms. `D`'s own
  tail ratio was 4.6 to 6.5 at depth 256 and 3.9 to 5.4 with nats.go.
- **RabbitMQ at 1,000.** Its checks of `B` held at 50 ms in three of four runs. The fourth had a
  retransmission on the delivering connection, which fails the checks at any bound. Every message of
  the three was certified, and `D`'s own tail ratio was 21 to 25.
- **Kafka on x86.** The client's part's own tail rose by 2.8 to 3.4 ms at normal priority (ratios 45
  to 51), and by 4 to 16 µs with the broker thread at real-time priority. With the broker thread at
  real-time priority, 54 to 64% of messages in the on-blocks and 79 to 84% in the off-blocks found
  no fetch waiting.
- **Kafka on the Arm pair.** The client's part rose by 1.9 to 2.1 ms at normal priority, and by −1
  to +11 µs with the broker thread raised. At normal priority a fetch was waiting for 96.2 to 99.6%
  of the off-blocks' messages, so the part's own tail there was 0.6 to 34.7 µs, and its on/off
  ratios 60 to 3,031.

Every prediction of this version holds on these runs.

## What could go wrong, and what it would mean

- **R-a or Q-a fails.** The load did not open the gap in that block, and its remedy is not tested
  here.
- **R-c, J-b or G-b fails while requests waited.** If the median ratio lies outside 1/1.2 and 1.2,
  `W` moved with the load on that broker. If it lies inside, these runs do not show that `W` held
  still. Under the rule these clauses fail often even where `W` holds still (D49-7).
- **`W` holds still while one of its parts moves.** If `Q`'s or the broker's residence's on/off
  ratio lies outside 1/1.2 and 1.2, a hold of `W` does not show that the load left `W` alone. In
  version 47's runs the off-blocks were not a neutral baseline: `F`'s off-block tail was the higher
  in all eight x86 Kafka runs, and `W`'s ratio was below 1 in 12 of the 16 runs where requests or
  credit waited. The record says so wherever it happens.
- **R-d fails while R-c holds.** Holding `W` within 20% does not keep a tenth of the rise out.
- **Q-b fails while Q-a holds.** A fetch thread that does nothing else does not keep the client's
  part out of the latency, and on Kafka the remedy is the check alone.
- **Q-c fails.** On this pair, a fetch thread that does nothing else leaves most messages a fetch
  waiting, and the round trip is a smaller part of Kafka's latency than version 47's runs showed.
- **G-a fails.** RabbitMQ's credit cannot be certified from the client's side at this bound on this
  testbed.
