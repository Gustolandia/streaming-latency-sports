# Freeze 43 (plan version 46): block U amended before any judged run

Written 22 October 2026, after freeze 42's pilot and before any judged run of block U. Freeze 42
(plan version 45, [`DESIGN.md`](DESIGN.md)) stays as it was fixed. This document says what
version 46 changes in it and why. Where it says nothing, version 45 stands.

**What prompted it.** Freeze 42's pilot ran three rounds and passed its instrument checks
([`README.md`](README.md)). A check of the design against the pilot's own runs, read after the
pilot and before any judged run, then found that several of the quantities the predictions read
would not mean what their names say. Every number below was read from the pilot's home copies, or
from block L's runs, with the repository's own readers.

*Words in this part.*
- **Lateness**: a message's actual send time less its planned send time.
- **Path floor**: the fixed delay one pair of TCP connections keeps for its whole life.
- **Duty**: the share of time stress-ng's workers are asked to compute.
- **Priming run**: an unjudged run that lets a freshly started broker do its first-run work before
  any measured run.

## What the check found, and what changes

| | Found in the pilot | Version 46 |
|---|---|---|
| 1 | Under 70% load at normal priority, Redis's producer at 2,000 messages a second sent a median of 24 ms late (272 ms at the 99th percentile, 84% of messages over 1 ms late), in runs the integrity rule passed, because it checks only the mean rate. Its sends came in bursts, and the consumer made about 36,000 requests against 88,000 idle. Block L's 88% Redis runs, which set U-c's Redis margins, were 0.5 and 0.9 s late at the median. The load changed what the broker received, not only the consumer. | The producer runs at real-time priority (SCHED_FIFO 80) in every setup, so only the consumer's priority varies between the loaded setups, and the real-time setup becomes the consumer-alone control. The integrity rule gains a lateness rule: the spread of lateness between its 1st and 99th percentiles at most 10 ms. |
| 2 | In every setup the clients paused 17-84 ms at about 24, 34, 46 and 60 s after the first send, each pause longer than the last. Leaving out the 0.25-0.53% of messages delivered after a turnaround over 10 ms lowered `W_so`'s 99th percentile by 4-16% and moved U-d's Redis ratio from 0.53 to 0.48. The pattern fits CPython's full garbage collections over the ~140,000 per-message objects the clients keep. | Both clients turn their collector off once connected (`gc.freeze(); gc.disable()`), and log any collection that still happens. Two pilot runs keep it on and log each collection, to check the cause. |
| 3 | The first run after the broker started was the one in which Kafka created its `__consumer_offsets` topic. That run acknowledged 1.42% of messages after more than 1 ms, against 0.10-0.36% in every other Kafka run at 2,000. On its own, it moved U-c's Kafka-2,000 share from 0.83 to 1.00. Every session recreates both brokers. | Each campaign starts with an unjudged priming run on each broker (`PRIME_S=60`). |
| 4 | The duty's second correction set stress-ng 4-5 points higher at real-time priority (76-77 against 72 at 2,000). Its law assumes one point of duty moves the measured background one point; the pilot's moved it 0.60-1.04. Real-time Kafka at 2,000 landed at 67.5%, half a point above the floor. | Each loaded setup's duty is frozen from the pilot, the duty it used with the second correction. Judged runs run open-loop at that duty, and the integrity rule still holds the measured background within 3 points of the design's load. The paper compares the two priorities at equal measured background, and says so. |
| 5 | On Redis the consumer acknowledges every 200 messages with a blocking XACK on the same connection, and version 45 timed the next turnaround from that acknowledgment's answer. Messages that arrived during that cycle were 2.5-3% of all messages under load, but 85-95% of `F`'s top 1%, and the split put their wait in the broker's term. | The turnaround runs from the answer to the previous request for messages, less the round trips of the connection's other requests in between, which are waits on the broker, not the thread's work. Those round trips become a term of their own, the acknowledgment wait. Version 45's turnaround is described beside it. |
| 6 | Each TCP connection keeps its own network delay. Within one Redis run, the 16 producer connections each sat at their own level of the split's first term, near 330, 500 or 590 µs, each only 10-20 µs wide. Kafka uses one connection each way, so each run draws one level: 328-356 µs in 7 pilot runs, 501-519 in 3, 585-618 in 8 and 655 in 1. | The split takes out each connection pair's path floor, and the decisions read only the rest. |
| 7 | `s_min` subtracts the request's and the acknowledgment's network crossings, so the broker's own bound `min(T_c, F_in − A_out)` is always at least as tight. `s_min` was exact for 2 of 80,174 flagged messages, and left 0.3-1.1 ms of the thread's time in `F`'s tail. | U-e's split uses the broker's bound. U-c stays on `s_min`, the bound it was fixed with, and the share with the broker's bound is described beside it. |
| 8 | U-c's share was a difference of 99th percentiles. Percentiles do not subtract, the share came out above 1 on one round, and it had no interval. Its 0.9 decision fired in 25-36% of simulated blocks per cell. | U-c's share comes from means over each run's own top 1% of `W_so`, so `W_so = F + s_min` holds in the setup's values. "The only path" needs the lower end of a run-level 95% interval to reach 0.9. |
| 9 | With each run drawing its own paths, a difference of means between runs at 50 a second cannot be read. Block L's Redis runs at 50 a second had `W_so` medians of 445, 473, 456 and 854 µs idle and 706, 443, 462 and 848 µs under load. L-b's "26% rise" is one more run drawing a slow path, and with no load effect at all its 10% test fails 64% of the time on Redis. | At 50 a second the loaded setup runs its load in 5-s blocks within each run, on then off. U-f compares, within the same runs and connections, the messages sent while the load was on with those sent while it was off. |
| 10 | Where the network interrupts ran, the scheduler's settings beyond the slice, and stress-ng's version and command lines were not recorded. The card's device was chosen by its place in a list. | Every run records them (`run_facts`), and the card is chosen by its MAC address. |
| 11 | Freeze 42's power was computed for 80-86% load. At the 70% the block runs, four rounds confirm U-c in 94% of simulated blocks at the pilot's effects, but in 61% with the load's excess halved, where the plan said 83%. U-d sat on its margin at 2,000 a second (0.50-0.53, against at most 0.5). | The rounds are set again by the same rule, from version 46's own pilot, before any judged run. U-a's real-time clause and U-d are simulated beside the rest. |

The margins (1.5, one half, 0.9), U-a's, U-b's and U-d's statistics, the pool's 99.5% and the card's
fold rule do not change.

## What is measured, as version 46 reads it

All on the driver's one clock, as in freezes 39 to 42, except where a line names the broker's or the
card's. Every definition in [`DESIGN.md`](DESIGN.md) holds except these.

- **The turnaround.** For each request for messages `k` on a consumer connection:
  - `t_ask(k)` is the receive timestamp of the answer to the request for messages before it on that
    connection;
  - `X(k)` is the time within `[t_ask(k), t_req(k)]` that the connection's other requests spent
    waiting on the broker, from each request's transmit timestamp to its answer's receive
    timestamp, counted once where they overlap.

  Then `T_c(k) = t_req(k) − t_ask(k) − X(k)`, zero where negative. It is the consumer thread's own
  time between two requests for messages. Version 45's `T_c45(k) = t_req(k) − t_before(k)` is
  described beside it.
- **The thread's saving and the thread-free latency.** As in version 45, with this `T_c`:
  - `s_min = min(T_c, max(0, t_req − t_rx_ack))`;
  - `s_max = min(T_c, max(0, t_req − t_tx_so))`;
  - `F = W_so − s_min`;
  - `F_lo = W_so − s_max`.
- **From the broker's capture.** Per message:
  - the time it lay stored and unasked-for, at least `S = max(0, F_in − A_out)`;
  - the broker's bound on the saving, `b_min = min(T_c, S)`, never below `s_min`;
  - `b_max = min(T_c, max(0, F_in − P_in))`.
- **The split, on one identity.** `W_so = floor + excess + hand + b_min + ack + wait + Q`, where:
  - `floor` is the message's connection pair's path floor: the 1st percentile of `W_so − R − Q` over
    the pair's messages in the run, or the least of them where the pair carried fewer than 100. The
    pair is the producer connection that carried the message and the consumer connection that
    delivered it;
  - `excess = W_so − R − Q − floor`: the network crossings and the producer's sending path below its
    timestamp, beyond their floor;
  - `hand = R − S`: the broker's handling of the produce request and of the answer;
  - `ack = min(X, S − b_min)`: what the consumer's other requests kept the message waiting, beyond
    the thread's own time;
  - `wait = S − b_min − ack`: the rest of its time stored and unasked-for;
  - `Q = t_rx_so − t_card`, as in version 45. Where no run of the block has card timestamps, `Q`
    folds into `excess`, as version 45 folds it into its first term.

  So `G = W_so − b_min − floor`, the latency with neither the thread's surely-added time nor the
  path's floor in it, splits exactly into `excess + hand + ack + wait + Q`. Version 45's split is
  described run by run.
- **New per run, described.** Each is read from a file the kit writes beside the run:
  - the producer's lateness after the warm-up: its 1st, 50th and 99th percentiles, their spread,
    and the share of messages more than 1 ms past the 1st;
  - the share of produce requests the broker held more than 1 ms before acknowledging;
  - the duty stress-ng ran at;
  - each client's count of collections;
  - the consumer thread's own counters, sampled just before each request
    (`/proc/thread-self/schedstat`). For each turnaround they give the time it waited for a core,
    the time it ran, and the rest, the sums and the means over the turnarounds above the run's
    99th percentile;
  - the number of connection pairs and the least and greatest floor;
  - the interrupt and scheduler facts of `run_facts`.

## Block U, as amended

On the second x86 pair, the base slice at 3 ms, no added delay, 70 s runs with a 20 s warm-up, as in
version 45. In every run:
- the producer runs at real-time priority;
- both clients run with their collector off;
- the consumer samples its own thread's counters;
- the run records its facts;
- the integrity rule holds the lateness spread to 10 ms.

Every run takes version 45's instruments: the socket timestamps at the device queue, both clients'
journals, the receiver's capture and both directions of the sender's, the card's receive capture
and the broker's capture, every capture with a 32 MiB buffer. Each campaign starts with a 60-s
priming run on each broker, unjudged and unread.

| Rate | Setups on each broker | Runs (Kafka and Redis, 4 rounds) |
|---|---|---|
| 2,000 msg/s, 70 s (20 s warm-up) | idle; 70% load, consumer at normal priority; 70% load, consumer at real-time priority | 24 |
| 500 msg/s, 70 s (20 s warm-up) | idle; 70% load, consumer at normal priority; 70% load, consumer at real-time priority | 24 |
| 50 msg/s, 70 s (20 s warm-up) | idle; 88% load in 5-s blocks, on then off | 16 |

That makes 64 runs in three campaigns, one per rate, with each round's setups in random order
(`u2000_design.json`, `u500_design.json`, `u50_design.json`). The loaded setups at 500 and 2,000 run
at the duty the pilot froze for each. The 50-a-second blocks run at a duty of 88, which gave 88.1% in
freeze 42's pilot, unless version 46's pilot shows the on-blocks outside 85-91%. The four rounds
stand until the pilot's power says otherwise.

## Predictions, as amended

A cell is one broker at one rate. Version 45's rules for cells out of reach, and for a clause that
fails, stand.

- **U-a (the turnaround grows under load, and real-time priority holds it):** unchanged, on the
  amended `T_c`. At 500 and 2,000 messages a second, on each broker:
  - `T_c`'s 99th percentile at 70% load is at least 1.5 times its value idle;
  - at 70% load, its value with the consumer at real-time priority is at most half its value at
    normal priority.

  A setup's value is the median over its passing runs.
- **U-b (the fix alone gives way where requests wait):** unchanged. `W_so`'s 99th percentile at 70%
  load and normal priority is at least 1.5 times its value idle, with the same decision as in
  version 45.
- **U-c (removing the turnaround takes the thread's part out):** at each rate and broker where U-b
  holds, the share of the rise that the turnaround removes is at least one half. The share is
  `1 − (F_load − F_idle) / (W_so,load − W_so,idle)`, read as follows:
  - each run gives the means of `W_so` and of `F` over its own messages above its 99th percentile of
    `W_so`;
  - a setup's value is the mean over its passing runs.

  - **Decision:** where the lower end of the share's 95% interval is at least 0.9, the paper says
    that the consumer's turnaround carries the load into `W_so` at that rate, on that broker. The
    interval comes from 2,000 draws of each setup's runs with replacement, from seed 20261022.
    Elsewhere the paper gives the share, its interval and U-e's split of the rest. Where U-b does
    not hold, the cell is not judged. Where U-b holds nowhere, the verdict is "not judged".
  - Described beside it: the share with version 45's turnaround, and with the broker's bound in
    place of `s_min`.
- **U-d (real-time priority keeps the consumer's thread out):** unchanged. At 70% load, `W_so`'s
  99th percentile with the consumer at real-time priority is at most half its value at normal
  priority.
- **U-e (where the rest lies, a decision rule):** at 500 and 2,000 messages a second, on each
  broker, take the rise of `G` from idle to 70% load at normal priority, measured as the mean over
  the messages above each setup's pooled 99th percentile of `G`. It splits exactly into `excess`,
  `hand`, `ack`, `wait` and `Q`.
  - **Decision:** the paper names the term that holds at least half of the rise. If no term does,
    it gives the split, each term's rise with its sign, and the floor's.
- **U-f (L-b's rise, a decision rule):** at 50 messages a second, on each broker, within the setup
  that runs its load in blocks, take the rise of the mean of `G` from the messages sent while the
  load was off to those sent while it was on. A message sent within 1 s after a switch is left out.
  The rise splits the same way.
  - **Decision:** the paper names the term that holds at least half of it. If `G` did not rise, it
    says so, and it gives each term's change with its sign.
  - Described beside it: the same comparison between the idle runs and the on-blocks.
- **The pool U-e and U-f read:** as in version 45. A setup's messages count over its runs whose
  split reaches at least 99.5% of their timed messages, and only the messages the split reaches.
- **Described, not judged:**
  - version 45's list;
  - the per-run additions above;
  - the wait that real-time priority takes from the turnaround (normal less real-time) and what it
    leaves (real-time less idle), at the median and the 99th percentile;
  - each setup described again with its failed attempts, read where their files allow;
  - the 99th percentile of `|W_so − W|` against the captures.

  Version 45's cost of the instruments, against block L's idle medians, stays described. The paths
  each run draws can move it by a few hundred microseconds, so it is not read as a cost.

## Pilot, round d (instruments only; the predictions above do not change)

One run of each of the sixteen setups (`up2000d`, `up500d`, `up50d`), each campaign primed. The
loaded setups at 500 and 2,000 run with the duty corrected a second time once the clients run
(`load_recorrect`), so that the pilot finds each one's duty. Two more runs at 2,000 messages a second
idle keep the collector on and log each collection (`ug2000`, unjudged and not read by the block's
reader). The pilot checks that:
- every run passes the integrity rule, the lateness rule among it, or that its failure is read;
- every message is found in the broker's capture and in the card's, and no capture drops a packet;
- the consumer's own counters are recorded, with time waiting for a core under load;
- the clients with their collector off made no collection, and those with it on show whether
  their collections fall on their pauses;
- the 50-a-second blocks hold 88% within 3 points while on and 0% within 3 points while off;
- the run facts are written.

**Before any judged run** the record states, and the push makes public:
- each loaded setup's frozen duty, the duty its pilot run used;
- the rounds, from `scripts/under_load_power.py --pilot-table` on the pilot's reading by
  `scripts/under_load.py read --pilot`;
- the pilot's values of U-a's real-time clause and of U-d;
- whether the pauses were the collector's.

The rules if the pilot fails:
- **The lateness rule fails at 70% at some rate.** Every loaded setup at that rate takes the
  highest load at which a second pilot round holds both the load and the lateness rules.
- **The blocks miss 88%.** Their duty is corrected by the miss and checked in a second round.
- **A client cannot run with its collector off.** That client logs its collections instead.

Each of these is stated before any judged run.

## What could go wrong, and what it would mean

- **A real-time producer takes processor time the load needs.** It does so in every setup, and the
  frozen duty is found with it running.
- **The collector off lets cyclic garbage build up.** A run lasts 70 s, and reference counting still
  frees what the clients drop. The logs say whether any collection ran.
- **The kernel may keep no run-queue time per thread.** The counters then say so, they stay
  described, and nothing is judged on them.
- **stress-ng switched on and off takes time to settle.** The second after each switch is left out.
- **A connection pair with few messages gets a floor from its least value,** which is noisier. The
  floors are described.
- **The consumer thread's counters are read just before each request,** so each costs that request a
  read of a few microseconds, the same in every setup.
