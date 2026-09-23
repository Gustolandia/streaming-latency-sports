# rdkafka_performance: the shakedown, and what it was measuring instead

23 September 2026, on the Arm pair, off the queue. This is the shakedown plan version 23 asks
for (D23-2): a short producer and consumer, tens of messages rather than thousands, with the
topic's partition count, the consumer's mode and its start offset written down, repeated until
the consumer reads what the producer sent. Nothing of this tool is measured until one does.

It matters more than the other ten. Of the eleven tools, this is the only one arranged with the
producer on the real clock and the consumer on the moved one, so it is the only one T2 can ask
its question of, and the only one that measures a one-way latency at all.

On its first outing it read nothing: its consumer took none of its producer's messages over a
whole staircase of ten steps, and again after the order of the two was reversed. A staircase of
ten steps that each measured nothing looks exactly like one where each measured zero, which is
why none of it was reported.

## The trials

Every trial: 50 messages of 512 bytes, `-l` on both instances, consumer started five seconds
before the producer, against a one-partition topic on the pair's own broker.

| | consumer arguments | what the consumer read |
|---|---|---|
| A | `-C -l -t sbl-tools` (topic absent) | **nothing**, timed out; producer delivered 50, to offset 49 |
| B | `-C -l -t sbl-tools` (topic now present) | **nothing**, timed out |
| C | `-C -l -t sbl-tools -p 0` | 100 — the 50 sent, and 50 left from A and B |
| D | `-C -l -t sbl-tools -p 0 -o end` | 50, exactly the ones sent |
| E | D, and `-r 50` on the producer | 50 |
| F | E, and `-X queue.buffering.max.ms=5` on the producer | 50 |

## What it was doing

**It was never attached to a partition.** The tool's own usage says `-p <num>  Partition
(defaults to random)`, and the invocation gave none. Trials A and B are the same invocation the
staircase ran, with and without the topic already there, and both read nothing: the topic's
existence is not what was wrong. Trial C is that invocation with `-p 0` and nothing else
changed, and it read every message. On a topic of one partition there is only one to attach to,
and the tool did not attach to it.

**Its start offset is the beginning, not the end.** The note in `tools_run.sh` said the consumer
"starts at the end of the topic", and the producer was moved to second place on the strength of
it. That was wrong: trial C read the fifty messages left over from A and B along with its own,
and reported their age as latency. `-o end` is what confines a run to its own messages.

**What it reports out of the box is its producer's batching.** With the consumer finally
attached, trial D's fifty readings were all about 1005 ms. Trial E paced the producer at 50
messages a second — the pacing every other tool in this block gets — and the readings fell in
exact 20 ms steps from 1005 ms down to 18 ms: every message stamped at its own enqueue time and
all fifty arriving together. That is `queue.buffering.max.ms`, which this example program sets
to a second, and which the consumer warns about inheriting. Trial F left everything else alone
and set it to 5 ms: median **7.34 ms**, spread 6.87 to 14.14. So the tool does measure a real
one-way trip once its consumer is attached, and its own default configuration reports a figure
dominated by how long the producer held the message before sending it.

## What changed, and what did not

The invocation now carries `-p 0`, `-o end` and `-r $RATE`. The first is what makes the tool
read anything at all; the second confines a run to its own messages; the third is the pacing the
other ten tools already get, through this tool's own option for it.

The one-second batching is left alone. Plan version 23 says the tools are run as their own
documentation runs them, and that a configuration a tool does not normally take is a second
reading beside the first and never in place of it. So the default stands and trial F is recorded
here as the second reading. That the default is what it is is not a defect to be tuned away: a
benchmark whose headline latency is mostly its own send-side batching is the kind of thing this
block exists to find.

## What this does not settle

T2's question for this tool is still open, and now for the first time it can be asked: the
producer stamps on the real clock and the consumer subtracts on the moved one, so a large enough
offset should push values below zero and make the tool show what it does with them. That is what
the next measured run is for. What the shakedown settles is only that the instrument is pointed
at something.
