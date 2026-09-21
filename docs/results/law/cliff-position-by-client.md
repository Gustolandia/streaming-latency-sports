# Each client has its own cliff, and the slice decides which part of it we stand on

**21 September 2026. Read off the calibration of the matched pair's session of 20 September
(`matched_20260920T234224Z`), 30 completed runs, both backends, three loads, one machine, one
night.** Not a test of any prediction: a calibration measures the instrument, and this is read
back off it.

**Words used here.** *Trip* — the real time from a message being sent to it arriving. *Got-it* —
the time from sending to the broker's acknowledgement coming back to the sender. *Negative
reading* — what a benchmark reports when it starts its clock at the acknowledgement and stops it
at arrival, and arrival came first. *Slice* — how long the scheduler lets a helper run before
switching. *Plateau, cliff, floor* — the three parts of the curve the law predicts.

## The thing that goes negative is not the trip

Worth stating plainly, because it is easy to lose. Our own trip is never negative, and a run
with one negative trip is stopped (P5a). What goes negative is **arrival minus the
acknowledgement**: the consumer already has the message before the producer is told the broker
took it. It is negative exactly when the acknowledgement loses the race to the delivery.

On A3's Kafka campaign, 19,952 messages at 75% load: 3.90% of readings were negative, and 3.90%
of messages had an acknowledgement slower than the whole trip. The same messages, to the message.

So the curve the law describes is a race, and what moves the cliff is how long the
acknowledgement's **tail** is. At 75% load with nothing added, on the same pair on the same
night:

| | got-it, median | got-it, 99th | the tail above the median |
|---|---|---|---|
| Kafka | 1.548 ms | 5.076 ms | 3.53 ms |
| Redis | 0.771 ms | 3.271 ms | 2.50 ms |

## Both clients have the cliff. They are not in the same place

The calibration walks each client from its own natural trip out to eight milliseconds added, so
it crosses the whole curve. The machine's own default slice, 2.8 ms on this 8-CPU driver.

| added | Redis trip | Redis negative | Kafka trip | Kafka negative |
|---|---|---|---|---|
| 0 ms | 0.766 ms | **62.91%** | 1.665 ms | 0.54% |
| 1 ms | 1.775 ms | 0.08% | 2.721 ms | 0.26% |
| 2 ms | 2.855 ms | 0.04% | 3.791 ms | 0.02% |
| 4 ms | 4.756 ms | 0.00% | 5.754 ms | 0.00% |

*(50% load. The other two loads show the same shape: Redis 21–28% at 75% and 13–23% at 88% with
nothing added, falling to 0.5–2.2% by one millisecond; Kafka 13.5–14.8% at 75% and 13.7–13.9% at
88%, falling to 2.3–5.3% by one to two milliseconds.)*

**Redis is not the quiet one.** At its own natural speed it is the noisiest thing in this
experiment: nearly two readings in three come out negative at 50% load. Its cliff is simply
further to the left — it falls between roughly 0.8 and 1.8 ms, where Kafka's falls between
roughly 2 and 4.

That follows from the table above it. Redis's acknowledgement is quicker and its tail is
shorter, so a growing trip overtakes that tail sooner.

## Why Redis then reads under 2% in the campaigns, and what that does and does not mean

A campaign does not place trips wherever it likes. It places them from the **slice**: the
plateau is read at 0.9 × slice and the floor past 2(slice + tick). At the 3 ms anchor that means
trips of 2.7 ms and up.

Kafka's natural trip is already 1.96 ms, so reaching 2.7 asks for about three quarters of a
millisecond, and it arrives there still partway down its slope. Redis's natural trip is 0.81 ms,
so reaching the same 2.7 asks for nearly two milliseconds — and by then it is well past its own
cliff and sitting in its floor.

So the reading that **"P3a and P4 cannot be tested on Redis, because its plateau is 0.55–1.15% at
the anchor slice"** is correct, and the guard that excludes it is right to. But the sentence
underneath it is not "Redis does not suffer from this". It is:

> At the trips a 3 ms slice asks for, Redis is already past its own cliff. The plateau those
> predictions need is at shorter trips than that slice reaches on this client.

The same thing happens to Kafka where its own curve allows: at 50% load Kafka reads 0.54% and
1.98% with nothing added, under the same 2% bar, which is why P3a is judged on 75 and 88% load
there. It is not a property of a backend. It is what happens to any client measured far enough
past its own cliff.

## What this does not show

These are calibration runs: one round, and the rates above are at each client's *natural* trip,
which is not where the plan defines the plateau (0.9 × slice). It is enough for "Redis's cliff
sits at a shorter trip than Kafka's, and both have one", which is what is claimed here. It is
not a measurement of either cliff's position, and no prediction is confirmed or refused by it —
P1 and P9 are what measure a cliff's position, against a slice set on purpose.

It also does not explain *why* Redis's acknowledgement tail is shorter. The obvious candidate is
that the two clients hand the stamp to different places — Kafka's producer acknowledges on a
background thread with up to 64 requests in flight, where Redis's client is request-and-reply —
and A8 is the block that tests exactly that, by taking the note on the background helper and on
the sending thread and comparing. This note does not anticipate its answer.

## Why it matters to the paper

It turns a limitation into a result. "Two predictions could not be tested on Redis" reads as a
gap in the work. What the data says is better than that, and more useful to a reader: **every
client has this cliff, they sit in different places, and where a benchmark stands on its own
client's curve decides whether it sees anything at all.** A practitioner measuring Redis at its
natural speed would meet a 63% negative rate. One who added two milliseconds anywhere in the
path — a slower network, a busier broker, a queue — would see nothing and conclude there was
nothing to see.
