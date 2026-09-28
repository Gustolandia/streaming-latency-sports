# The strange results of the final judging, each read to its cause as far as the data go

**28 September 2026, on the same runs and the same answers as the final judging.** This reads
every result the [final judging](judged-with-and-without-the-brake.md) left strange, and sets down
the formula each expected result fell under. **All of it is read after the fact.** No verdict
changes: every prediction keeps the answer its frozen judge gave, and nothing here is a test of
anything the plan predicted. What it adds is why. Four programs read it, each at 100% branch
coverage: [`m0_bursts.py`](../../../scripts/m0_bursts.py),
[`pause_census.py`](../../../scripts/pause_census.py),
[`cliff_shape.py`](../../../scripts/cliff_shape.py) and
[`a9_decompose.py`](../../../scripts/a9_decompose.py). Their answers are in
[`strange-results-28-sep/`](strange-results-28-sep/), and every number below is recomputed from
those files, or from the final judging's own answers, by `test_strange_results_28_sep.py`.

**Words used here.** A *trip* is the real time from a message being sent to it arriving; *got-it*
is the time from sending to the broker's acknowledgement coming back. A *negative reading* is what
a benchmark reports when it starts its clock at the acknowledgement and arrival came first. The
*slice* is how long the scheduler lets a task run before switching; the *tick* is the timer
interrupt the kernel wakes on. The *free reading* of a cliff is a curve required only never to
rise; the *fitted shape* is a plateau, a straight fall and a floor. *Post hoc* means read after the
data were seen, which is why nothing here decides anything.

## What each strange result was

*Plain words:* three are explained completely and three in large part, two are faults in how the
judges read the data, one is a new finding about the instrument, and five stay open.

| Result | What it was | Where |
|---|---|---|
| M0: Redis's trip grows 1.18 and 1.31 times the delay | Burst followers wait one or more extra delayed round trips; the median straddles two kinds of message | [M0](#m0-the-median-straddles-two-kinds-of-message) |
| M0: the recording moved Redis's trip most at 8 ms | At 8 ms the median is the leaders' upper tail, and the recording moves the tail | [M0](#m0-the-median-straddles-two-kinds-of-message) |
| Pauses of seconds on both x86 pairs | Two kinds: the driver's disk writes stalling, and Kafka's broker stalling | [Pauses](#the-pauses-are-two-faults-and-neither-is-the-network) |
| The fitted shape fails where the free reading holds (P1, P7 and P9; P2d) | There is no flat plateau: the rate falls from the shortest trips, much as a helper waiting out the rest of a slice would make it | [The cliff](#the-cliff-has-no-flat-plateau) |
| P2 and P2b never confirmed | The judges read both of A2's slices as one curve; they could not confirm P2 in a world where the law holds exactly | [The tick](#p2-p2b-and-p2c-read-two-slices-as-one-curve) |
| A9-2 predicts six to ten times too few | A9-2 counts time and A9-2b counts acknowledgements; the ratio of the two is a product that comes to about a tenth | [A9](#a9-2-counts-time-a9-2b-counts-acknowledgements) |
| A9's recording, new here | It raised the negative rate it recorded, by about half for Kafka and four times for Redis | [A9](#a9s-recording-raised-the-rate-it-recorded) |
| P6 predicts 2.5 to 13 times too many | In part: it counts every thread's waits, where the rate follows the stamping thread's; A6's histogram holds about as many waits as A9's wake-ups alone | [P6](#p6-the-histogram-looks-like-the-wake-ups-alone) |
| P4 not confirmed | Redis's plateau is under the 2% P4 makes its claim on, and its judge words that "not confirmed" | [P4](#p4-makes-no-claim-on-redis-and-its-judge-says-not-confirmed) |
| P3a, P8, P1 on Kafka, A9-1, and A9-2b on two parts | Open, each with what is known | [Open](#what-stays-open) |

## M0: the median straddles two kinds of message

*Plain words:* in the football replay, 46% of the messages arrive a moment behind another message
of the same burst. Redis hands the waiting reader only the first; each of the others waits out an
extra round trip that the delay lengthens. The first ones grow one for one with the delay, the
others two to six times as fast, and the median sits where the two kinds meet, so it grows faster
than the delay. None of the four explanations M0 froze is this one, though M-H2 names the loop it
lives in.

**Bursts.** The football match schedules every event of one match second for the same instant.
Over M0's measured messages **4,020 of 7,490 (53.7%) lead their burst** and the other 3,470 follow
it, the same at every delay. A burst's *leader* is the first message the broker took; its
*followers* are numbered r = 1, 2, … in the order the broker took them (a Redis stream's own ids;
for Kafka, the order they were sent).

**The growth of each message's trip follows from the receive loop's own rules, with nothing
fitted.** Write k for how many delayed replies a message waits for:

- **Kafka:** k = 1 for every message. The producer sends a burst in one request and the consumer
  fetches it in one answer.
- **Redis, acknowledging in batches of 200:** k = 1 for the leader, whose read was already waiting
  at the broker, and **k = 2** for a follower, which waits for the leader's delayed answer to land
  before the next read is even sent, and then for its own.
- **Redis, acknowledging each message:** **k = r + 2** for follower r: those two, and one delayed
  acknowledgement round trip for each message stamped before it in the same answer.

So a message's trip at added delay d is **T(d) = T(0) + k d**. Measured, from no delay to 8 ms, by
rank:

| Part | Leader | Follower 1 | Follower 2 | Follower 3 | Follower 4 |
|---|---|---|---|---|---|
| Kafka (rule: 1, 1, 1, 1, 1) | 0.993 | 0.997 | 1.001 | 1.006 | 0.985 |
| Redis, batches of 200 (rule: 1, 2, 2, 2, 2) | 0.996 | 2.016 | 2.019 | 2.022 | 1.952 |
| Redis, one at a time (rule: 1, 3, 4, 5, 6) | 0.995 | 3.075 | 4.143 | 5.197 | 6.267 |

**The median of the two kinds.** A run's median trip M(d) is where its messages, each grown by its
own k d, cross one half:

  Σ_r π_r F_r(M(d) − k_r d) = ½,

with π_r the share of messages of rank r and F_r the distribution of their trips at no delay.
Moving every message of the zero-delay runs by its own k d and taking the median predicts the
slope M0 measured, with nothing fitted:

| Part | Slope, all runs | Recorded runs (M0's reading) | Unrecorded | Predicted from the zero-delay runs |
|---|---|---|---|---|
| Kafka | 0.990 | 0.995 | 0.997 | 1.000 |
| Redis, one at a time | 1.137 | 1.181 | 1.125 | 1.148 |
| Redis, batches of 200 | 1.233 | 1.307 | 1.193 | 1.229 |

**It is a step, not a slope.** The leaders are more than half the messages (π₀ = 0.537), so once
every follower has passed the median, M(d) = d + Q₀(1/(2π₀)), where Q₀ is the leaders' own quantile
at no delay, here their 93.2nd percentile. From then on the departure stops growing, at Q₀(0.932) −
M(0) = **1.50 ms** for Redis acknowledging each message and **2.09 ms** in batches of 200. With the
faster followers (k ≥ 3) the step is complete by 2 ms: the median grows 3.50 ms from 0 to 2 ms and
5.95 ms from 2 to 8, one for one. With k = 2 it is still forming at 2 ms. A straight line through a
step at 0, 2 and 8 ms reads it as a slope of 1 + 0.096 × the step. That is why batching, the change
M0 made to shorten Redis's loop, shows the *larger* departure: its followers stay near the median
longer.

**Why M-H2 was dropped although it names the loop.** M-H2's frozen test replays each run's
messages through the loop's rules with fixed costs, so every leader gets the same replayed trip.
With the leaders over half, the replayed median is always a leader's trip, d plus a constant, and
its slope is one whatever the followers do. In **all 12 and all 13 recorded Redis runs**, the
replayed median is the replay's smallest trip, shared by 53.7 to 61.4% of its messages. The
replay does place the followers: at 8 ms it gives the other messages medians of 25.8 to 26.0 ms
(one at a time) and 17.1 (batches), where the runs' first followers measured 27.2 and 18.1. The
test, as frozen, could not keep M-H2 in any run whose leaders are more than half, and M-H2 keeps
its frozen answer: dropped.

**The recording's own effect** (0.65 ms at 8 ms, against the 0.02 the plan allows) is the same
mechanism seen from the other side. The recorded runs' leaders sit 0.02 to 0.06 ms above the
unrecorded runs' in the middle, and 0.09 to 0.60 ms above them at the 93.2nd percentile. At 8 ms
the median *is* that percentile, so it moves by the tail's amount: **+0.601 ms one at a time and
+0.524 in batches, exactly the leaders' 93.2nd percentile's move**. At no delay, where the median
sits among many messages, it moves 0.09 to 0.14 ms. Kafka's median moves 0.35 to 0.43 ms at every
delay: where every message grows alike, the median never moves onto the tail.

## The pauses are two faults, and neither is the network

*Plain words:* a message more than 150 ms late is a pause. On the x86 pairs 221 runs had one. In
152 episodes only the receiving side stopped: the consumer and a second, unrelated process on the
same machine stopped writing together, while the processors sat waiting on the disk. In 116 the
Kafka broker itself stopped. Redis's broker, which writes nothing to disk, never did. The Arm pair
had one episode of 0.2 s in 2,159 runs.

A pause's late messages are released together, so they are read as *episodes*: late messages
released within a second of each other are one. There are **269**: 152 on the receiving side
(Kafka and Redis), 116 at the broker (Kafka only), and one of 20.6 s that was both.

| | Receiving side | Broker (Kafka) |
|---|---|---|
| Episodes | 152, Kafka and Redis | 116, Kafka only |
| Median, longest | 1.0 s, 15.8 s | 0.41 s, 11.4 s |
| The broker's acknowledgements | back as usual (every one under 150 ms) | held as long as the deliveries |
| The load sampler, another process on the driver | stopped too, in 74 of 76 episodes of a second or more | on time in all 29 |
| The broker's log | | in 12 of 15 episodes of 3 s or more, the broker could not heartbeat its own controller |

**The receiving side: disk writes on the driver.**

- **The sampler stopped with the consumer.** `util_sampler.py` shares nothing with the messages: it
  reads the processors' counters and writes a line every half second.
- **The processors were waiting on the disk.** Runs with a receiving-side pause of a second or more
  spent a median of **2.97 CPU-seconds** (first x86) and **2.96** (second x86) idle while a task
  waited on the disk; runs with no pause spent **0.09**. Over the 69 paused runs the disk wait grows
  **1.08 CPU-seconds per second of pause** (correlation 0.64). Other tenants took no processor
  time from any of the 8,092 runs that record it.
- **The producer, on the same machine, did not stop.** It keeps its rows in memory and writes its
  file once, at the end of the run. The consumer writes as it goes, and so does the sampler.
- **The consumer was not waiting on the network.** In the 48 Redis episodes of half a second or
  more, the consumer spent at most **4%** of the pause inside a read of the broker. The longest,
  15.8 s, began just after it stamped a message, and its next read began 15.8 s later; that
  campaign acknowledged in batches, so no network call fell in the gap.

**The broker side: Kafka's controller.** The broker ran in KRaft's combined mode: the broker and
the controller that keeps its metadata live in one process, and the controller writes each change
to its metadata log on disk before going on. Redis was started with persistence off (`--save ''
--appendonly no`) and writes nothing. In the long broker-side episodes the broker logged that it
could not heartbeat its own controller. That fits a controller held up on a disk write, as the
driver's writers were held up, but the broker's own disk wait was never recorded, so this is the
likeliest reading and not a shown one.

**Why x86 and not Arm.** The x86 machines boot from their disk through NVMe; Azure offers only SCSI
for the Arm sizes, and they use it (the testbed file records both). All six have the same disk
(Premium SSD, 64 GB). One pause in 2,159 Arm runs against 112 in 3,197 and 109 in 2,746 on x86 is
that contrast, but the processor and the host differ as well, so the disk path is not isolated.

**A lead, not a finding.** The receiving-side pauses of a second or more fall in the first quarter
of the clock hour in **35 of 68 runs**, against the 17 an even spread gives (Rayleigh test p =
0.002, mean minute 12.5), on both pairs. Nothing the kit installs runs hourly: it switches off the
package timers, its only scheduled line starts the queue at boot, and the watch polled every five
minutes from home. What woke at those minutes is not recorded.

**What they cost.** The final judging counted these runs and nothing is judged again without them.
A late message is not a negative one, so a pause can only thin a run's negative rate, by at most
the share of messages it held.

## The cliff has no flat plateau

*Plain words:* the law's formula says the rate stays flat for every trip shorter than the slice.
Measured, it keeps falling all the way there: at half the slice it is 1.5 to 4 times its level at
0.9 of the slice. A straight line drawn through a curve like that starts its fall too early and
moves too little when the slice moves. That is every "fitted shape fails, free reading holds" in
the final judging.

The plan's formula, with slice s, tick h, how often the helper is kept waiting p, and the floor c:

  r(D) = c + p × { 1 for D ≤ s;  (s + h − D)/h for s < D < s + h;  0 for D ≥ s + h }.

**Measured, the rate at half the slice is 1.45 to 3.94 times the rate at 0.9 of it**, at every
slice where the runs reach half the slice, and more at the larger slices. On the first x86 pair,
Redis: 1.45 at 2.25 ms, 1.97 at 3 ms, 3.38 at 4.5 ms and 3.04 at 6 ms; Kafka: 3.44 at 4.5 ms and
2.75 at 6 ms. On the Arm pair, Redis: 1.61, 2.16 and 3.94 at 1.5, 3 and 4.5 ms; Kafka: 3.36 at 4.5
ms.

**A shape that falls from the start.** A helper kept waiting wakes at no particular moment of the
other task's slice, so it waits out the *rest* of it, R, uniform between 0 and s, and then until
the next tick, U, uniform between 0 and h. A reading turns negative when that wait outlasts the
margin x = T − g, the trip less the got-it:

  r(T) = c + p × P(R + U > T − g),

  P(R + U > x) = 1 − x²/(2sh) for 0 ≤ x ≤ m;  1 − (x − m/2)/M for m ≤ x ≤ M;
                 (s + h − x)²/(2sh) for M ≤ x ≤ s + h;  0 beyond,  with m = min(s, h), M = max(s, h).

It has no plateau. It falls in a straight line from the start, with rounded ends, and it still
ends at s + h. Neither shape is fitted: each run keeps its own trip, slice, tick and got-it, and
only its measured rate is replaced by the shape's. A scale or a floor moves no halfway point, width
or start, so neither shape carries one.

**Through the frozen judges.** Each shape in place of the data, judged exactly as the data were:

| | Data: free, fitted | The plan's formula | The rest of a slice and a tick |
|---|---|---|---|
| P1 slope, Kafka (first x86) | 0.758, 0.230 | 0.997, 0.998 | 0.922, 0.519 |
| P1 slope, Redis (first x86) | 1.007, 0.662 | 1.000, 0.999 | 0.930, 0.680 |
| P9 slope, Kafka (Arm) | 0.830, 0.285 | 0.889, 0.908 | 0.802, 0.525 |
| P9 slope, Redis (Arm) | 1.153, 0.798 | 1.000, 1.005 | 0.954, 0.723 |

The plan's formula gives both summaries nearly the same slope, near one. The rest-of-a-slice shape
gives the split the data show, a free slope near one and a fitted one far below it, and on Redis it
gives nearly the measured numbers. The fitted cliff starts (P2d) show it too: on Redis at the 3 ms slice
the data's fitted start is 1.50, 1.37 and 1.86 ms at ticks of 1, 4 and 10 ms; the plan's formula
gives 3.01, 3.02 and 3.01; the rest-of-a-slice shape 1.50, 2.02 and 2.11. Level by level, as shares
of the rate at 0.9 of the slice, the rest-of-a-slice shape sits **0.175** from the data on average
over 94 points, against **0.290** for the plan's formula (0.091 against 0.121 past half the slice).

It is not the whole story. At 4.5 and 6 ms the data's rate at half the slice is 2.75 to 3.94 times
its level at 0.9 of the slice, where the rest-of-a-slice shape gives 1.61 to 2.36: the measured
curve falls faster still before the slice. Past the cliff, at s + 1.5h, Kafka keeps 0.24 to 0.42
of its plateau, where the shape keeps 0.22 to 0.26 and the plan's formula none. And Kafka's free
slope, 0.758, stays below what either shape gives the same design.

## P2, P2b and P2c read two slices as one curve

*Plain words:* A2 measured two slices, 1.5 and 3 ms, in every kernel. The programs judging the
tick put both slices' runs into one curve per kernel, so the "width" they read runs from the first
slice's cliff to the second's. Fed the law itself, with no noise, they still would not have
confirmed P2 or P2b. Read one curve per slice, as the design has them, the width follows the tick
at the 1.5 ms slice.

A2's setups are "2 slices × 8 trips placed with that kernel's tick"; a cliff is one slice at one
tick. `law_predictions.width_follows_tick` and `width_against_tick` group A2's runs by tick alone,
where P2d's judge groups them by tick and slice. **In a world where the plan's formula holds
exactly**, each run's rate replaced by the formula's at its own trip, the frozen P2 judge returns a
width ratio of 1.98 (free) and 1.57 (fitted) on Redis, against a band of 2.5 to 5.5, and P2b 4.19
and 2.99, against 6 to 14. On Kafka its free reading returns nothing and its fitted one 9.69 and
20.4. Read one curve per slice, the same world gives 4.0 to 5.2 for P2 and 9.8 to 12.0 for P2b, both
inside their bands, at both of Redis's slices and at Kafka's 3 ms. Kafka's 1.5 ms slice is the
exception: a trip cannot be made shorter than the client's own trip with nothing added, and at
HZ=1000 most of that slice's cliff lies below Kafka's, as the 2.25 ms slice did in A1.

On the data, read one curve per slice (post hoc):

| Backend, slice | Width on the tick, free | Width on the tick, fitted | Ratio at HZ=100, free, fitted (P2b's band: 6–14) |
|---|---|---|---|
| Kafka, 1.5 ms | 1.36 + 0.70 h | **0.04 + 1.04 h** | 3.84, **7.31** |
| Kafka, 3 ms | 2.08 + 0.55 h | 1.15 + 0.69 h | 2.39, 3.60 |
| Redis, 1.5 ms | **−0.25 + 0.92 h** | **−0.61 + 1.15 h** | **7.90, 7.80** |
| Redis, 3 ms | 0.35 + 0.57 h | 1.48 + 0.81 h | 4.41, 3.35 |

At the 1.5 ms slice, in the cells in bold, the width is proportional to the tick, with a slope near
one and an intercept near zero, which is P2c's statement, and P2b's ratio sits in its band. At the 3 ms slice it grows
less than in proportion and carries an intercept: there the slice's own remainder spreads the fall
as much as the tick does. The rest-of-a-slice shape gives the same pattern (Redis at 3 ms, fitted:
1.62 + 0.87 h, against the measured 1.48 + 0.81 h). None of this is a verdict: P2, P2b and P2c keep
their frozen answers.

## A9-2 counts time, A9-2b counts acknowledgements

*Plain words:* A9-2 asks what share of the time the stamping thread spends in the part of a wait
beyond the margin; A9-2b asks what share of acknowledgements met a wait beyond it. At 50 messages
a second the first comes to about a tenth of the second, and the arithmetic says exactly why.

For a run whose stamping thread waited W₁ … W_N for a CPU over a window of length D, with margin
m = T − g, A9-2 is Σ max(0, Wᵢ − m) / D. With one stamping thread, as every A9 recording has,

  A9-2 = (N/D) × P_w(W > m) × e(m):

the waits a millisecond, the share of them that outlast m, and by how much on average they do
(e(m), the mean excess). A9-2b is P_ack(W > m), the share of acknowledgements whose own wait
outlasted m. So

  A9-2 / A9-2b = (N/D) × e(m) × P_w / P_ack.

| Pair, backend | A9-2 / A9-2b | Waits a second | e(m), ms | (N/D) × e(m) | P_w / P_ack |
|---|---|---|---|---|---|
| Arm, Kafka | 0.076 | 532 | 0.61 | 0.311 | 0.242 |
| Arm, Redis | 0.095 | 404 | 0.49 | 0.264 | 0.430 |
| first x86, Kafka | 0.116 | 383 | 0.87 | 0.317 | 0.351 |
| first x86, Redis | 0.145 | 364 | 0.69 | 0.266 | 0.655 |
| second x86, Kafka | 0.097 | 354 | 0.77 | 0.289 | 0.387 |
| second x86, Redis | 0.161 | 392 | 0.71 | 0.280 | 0.554 |

Each column is a median over the part's recorded runs, and the identity holds run by run, in all
268 runs it could be read on. Both factors are below one. The thread waits 354 to 532 times a
second, far more often than acknowledgements come (50 a second), and its waits outlast the margin
by only 0.49 to 0.87 ms on average, so (N/D) × e(m) comes to 0.26 to 0.32. And most of its waits
are short ones between acknowledgements: a wait picked at random is 0.24 to 0.65 times as likely as
an acknowledgement's own wait to outlast the margin. A9-2b counts the waits that matter, one per
acknowledgement, which is why it comes close.

## A9's recording raised the rate it recorded

*Plain words:* in the half of A9's runs that recorded every thread's scheduling events, the
negative rate came out higher than in the half that did not: about half as high again for Kafka
and four times for Redis. The recording is not a bystander.

Each A9 setup's recorded runs' mean negative rate over its unrecorded runs', the median over
setups: **1.36, 1.49 and 1.39 for Kafka** on the Arm, first and second x86 pairs, and **4.33, 3.69
and 3.75 for Redis**. A6's recording in A1's and A3's runs, one histogram kept inside the kernel,
read the same way: 0.89 to 1.06, which is nothing. A9's tracer prints a line for every scheduling
event of every python3 thread, and it is that recording, not recording as such, that disturbs the
machine. A9's readings therefore describe the system with that recording on. A9-2b's prediction and
the rate it is held against come from the same recorded runs, so that comparison stands, but
neither is the rate of an unrecorded run.

## P6: the histogram looks like the wake-ups alone

*Plain words:* P6's recording counts the waits of every python3 thread in one histogram. It holds
about as many waits as A9's event recordings show after wake-ups alone, with about the same share
of long ones. The waits after preemptions that A9 shows, 2.6 to 4.4 times as many and almost all
short, are not in it, and they are likeliest the event recording's own doing. That leaves the
histogram as the truer picture of the waits, and P6's over-prediction without a full account.

| Pair, backend | A6 histogram: waits a run, share over 1 ms | A9: waits after a wake-up, share over 1 ms | A9: waits after a preemption, share over 1 ms |
|---|---|---|---|
| Arm, Kafka | 36,549, 11.1% | 32,424, 14.5% | 143,187, 0.4% |
| first x86, Kafka | 36,870, 13.1% | 32,450, 17.5% | 96,345, 0.9% |
| first x86, Redis | 33,122, 13.5% | 31,159, 13.9% | 111,393, 0.8% |
| second x86, Kafka | 36,747, 13.6% | 32,500, 16.6% | 84,147, 0.9% |

Two readings fit the counts. A6's tracer may miss the preemption waits: counted, they would cut its
share of long waits several times over, which is the size of P6's over-prediction on Kafka (2.5 to
3.2). Or A9's tracer causes them. The control above favours the second: A6's recording left the
negative rate where it was and A9's did not, and a tracer that takes processor time from the
threads it traces makes them wait after preemptions. On that reading the histogram is right, and
P6 over-predicts because it counts every python3 thread's waits, where the rate is set by the
stamping thread's wait for each acknowledgement, which A9-2b counts and which comes close. That
the other threads' waits outlast the margin more often than the stamper's own is the part not
read here.

## P4 makes no claim on Redis, and its judge says "not confirmed"

*Plain words:* P4 says go-first removes the plateau "wherever the ordinary plateau is at least 2%".
Redis's is 0.69%, so P4 says nothing about Redis. The judge still reports that part as not
confirmed, where version 30 made parts like it "out of reach" for the other predictions.

In A7 the ordinary plateau (the rate at 0.9 of the slice) is **0.0405** for Kafka and **0.0069**
for Redis; go-first takes both to **0.0000**. `priority_removes_the_plateau` gives a part under the
bar no number and does not mark it untested, so `verdict` calls the whole "not confirmed" rather
than "confirmed where tested". Read by the plan's own clause, P4 is confirmed on the one backend
it makes a claim on. The frozen answer stays "not confirmed".

## What stays open

*Plain words:* five results keep no cause.

- **P3a.** Every campaign's cliff moved a little earlier at 88% load than at 75%: the free halfway
  point by −0.009, −0.188, −0.086, −0.011 and −0.309 ms. The plan's band is ±0.25 ms, and the
  intervals reach past it. Nothing read here explains the direction.
- **P8.** Python's plateau is 3.25 (x86) and 4.25 (Arm) times Java's, where P8 allows 1.5. The
  records of 22 September found the shape the same in both clients and the size a property of the
  machine. The cause of Python's larger plateau is not read here.
- **P1 on Kafka.** Its free slope, 0.758, is below what either shape above gives the same design
  (0.997 and 0.922).
- **A9-1.** It asks that 90% of negative readings spent most of their interval waiting for a CPU.
  The share is 79 to 92%, and the stamping thread spent 21 to 35% of the interval running: it was
  busy, not only kept waiting. A9-1 holds only for Redis on x86.
- **A9-2b on Kafka on the Arm pair and on the second x86 pair.** It over-predicts at 75% load
  (median ratio 1.51 and 1.46) and comes to 0.87 and 0.96 at 88%. No cause is found for the
  difference between the loads.

## The results that came out as expected, and the formula each fell under

*Plain words:* these are the parts of the programme where the data did what the formula said. The
formula is in the middle, the measured number on the right.

| What was expected | The formula | Measured |
|---|---|---|
| Load raises the plateau (P3b), five campaigns on three machines | Δp = p(88%) − p(75%), its 95% interval above 0 | +0.048 (0.044 to 0.052), +0.047 (0.043 to 0.051), +0.048 (0.042 to 0.056), +0.041 (0.036 to 0.045), +0.050 (0.048 to 0.053) |
| The cliff follows the slice, read freely (P1 on Redis; P9 on both) | H(s) inside [s, s + h] at each slice in reach, and dH/ds between 0.8 and 1.2 | Redis, first x86: 1.007 (0.844 to 1.169), 5 of 5 slices in band; Arm: Kafka 0.830 and Redis 1.153, every slice in band |
| The cliff's middle in its band on Kafka (P1) | H(s) inside [s, s + h] | 4 of 4 slices, read freely |
| Default slices follow the core count (P7's read-back) | s(n) = s₀ × (1 + log₂ n), s₀ read off the kernel: 0.7 ms on the second x86 pair's, where A5 ran | 1.4, 2.1 and 2.8 ms read back at 2, 4 and 8 CPUs |
| The width grows in proportion to the tick (P2c on Redis, fitted) | w(h) = a + b h, b's interval overlapping 0.8 to 1.2, a's including 0 | b = 0.874 (0.807 to 1.034), a from −0.16 to 1.79 |
| Go-first removes the plateau (P4 on Kafka) | p / p_go-first at least 5, its interval above 2 | 0.0405 to 0.0000 |
| Java has the same cliff, and go-first removes it (P8's first two clauses) | r(0.9s) > r(s + 0.5h) > r(s + 1.5h); p / p_go-first at least 5 | the cliff in 2,000 of 2,000 draws on both pairs; cut 1,227 times (x86) and 184 times (Arm) |
| The stamping thread's own waits predict the rate (A9-2b), four of six parts | r̂ = (1/N) Σ 1[W_ack > T − g]: two thirds of setups within 0.67 to 1.5, median at least 0.8 | Arm Redis 26 of 28, median 1.12; first x86 Kafka 22 of 28, 1.18; first x86 Redis 24 of 29, 1.30; second x86 Redis 12 of 15, 1.11 |
| Negative readings find the stamper waiting (A9-1, Redis on x86) | at least 90% mostly waiting | 91.7% and 91.1% (first x86), 92.0% and 91.6% (second), at 75 and 88% load |
| Kafka's trip grows one for one (M0) | T(d) = T(0) + d | 0.995 (0.974 to 1.022) on the recorded runs, 0.997 unrecorded; every rank 0.98 to 1.01 |
| The delay reaches the receiver as set (M-H1) | arrival shift within 0.05 ms of the 8 ms held | 8.04 (one at a time), 7.97 (batches) |
| Burst leaders grow one for one, followers by whole round trips (post hoc) | T(d) = T(0) + k d, k from the loop's rules | leaders 0.995 and 0.996; followers 2.02 (batches), 3.07, 4.14, 5.20 and 6.27 (one at a time) |
| A floor past the cliff | r(2(s + h)) = c, small | 0.0000 to 0.0001 at twice the slice plus a tick, A1 and A4 |
| At the 1.5 ms slice, the width in proportion to the tick (post hoc, per slice) | w(h) = a + b h, a near 0, b near 1 | Kafka, fitted: 0.04 + 1.04 h; Redis: −0.25 + 0.92 h free, −0.61 + 1.15 h fitted |

## How this was read

Every campaign as the final judging read it (`runs/azure/final_campaigns`, rebuilt and checked on
27 September; the runs themselves are not in this repository):

```bash
python scripts/m0_bursts.py --runs runs/azure/final_campaigns/matched/m0_20260926T133519Z --out docs/results/law/strange-results-28-sep
python scripts/pause_census.py --root runs/azure/final_campaigns --out docs/results/law/strange-results-28-sep
python scripts/cliff_shape.py --root runs/azure/final_campaigns --out docs/results/law/strange-results-28-sep
python scripts/a9_decompose.py --a9 <the five A9 campaigns> --a6 <A1's seven and A3's five campaigns> --out docs/results/law/strange-results-28-sep
```

## Pocket dictionary

- **Burst, leader, follower**: the events of one match second, sent at one instant; the first the
  broker took, and the ones behind it.
- **Episode**: the late messages of one pause, released together.
- **Free reading / fitted shape**: a curve required only never to rise, and a plateau, a straight
  fall and a floor; a prediction passes only where both agree.
- **iowait**: time a processor sat idle while a task waited on the disk.
- **KRaft combined mode**: Kafka running its broker and the controller that keeps its metadata in
  one process.
- **Margin (T − g)**: how long a wait must last for a reading to turn negative.
- **Post hoc**: read after the data were seen; it can explain, not test.
- **Rest of a slice**: what is left of another task's protected run time when the helper wakes.
- **Step**: a rise that happens once and then stops, which a straight line reads as a slope.
