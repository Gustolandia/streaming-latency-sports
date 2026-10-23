# The Java client, for A8

A8 asks whether the effect belongs to our Python client or to the machine. Kafka's official client
is written in Java, so answering it needs a Java producer and consumer that differ from the Python
ones in the client and in nothing else.

That is what these are. The plan is read and ordered the same way, the message carries the same
fields with the same key, the settings are the same (acks=all, no lingering, one request in
flight), and the files written are the same two CSVs with the same columns, so the analysis cannot
tell which client produced a run.

## The three stamps, and why the third is the point

    t_prod_sched_ns   when the plan said the event should go
    t_prod_send_ns    the wall clock immediately before the send
    t_broker_ack_ns   the wall clock when the broker's acknowledgement is seen

Where the third is taken decides what it measures. In the callback it is stamped on the client's
own background thread, so it waits for that thread to be scheduled and carries the wait inside it.
Inline it is stamped on the sending thread the moment the future resolves, and never pays that
wait. Both clients offer both, and A8 runs both.

## The clock, and why it can refuse to run

Producer and consumer are separate processes, so both read the wall clock: a monotonic clock's
origin is process-relative and would add each process's start offset to every latency.

Java's `Instant.now()` and Python's `time.time_ns()` ask the operating system the same question
and do not always get an answer of the same fineness. Measured, by stepping each clock until it
changed:

    Windows 11          JVM     Instant.now()    998600 ns
    Windows 11          Python  time.time_ns()   998600 ns
    Ubuntu 22.04 arm64  JVM     Instant.now()      1000 ns
    Ubuntu 22.04 arm64  Python  time.time_ns()      232 ns

Two things follow. The first is why the guard exists: on the development machine both clocks step
in about a millisecond, to the same figure. That is the operating system's answer, not the JVM's
-- Python is no better there -- so it is not a reason to prefer one client, it is a reason not to
measure on Windows at all. Our trips run from under a millisecond to about fourteen, and the cliff
the law predicts is one millisecond wide, so such a clock would report tidy whole numbers and see
none of the structure. A8 is therefore run on Linux, and the client enforces that itself rather
than trusting anyone to remember. The Python client has no such guard, which is the asymmetry to
close next: it would have run on that clock without complaint.

The second is a difference we carry rather than remove. On the testbed the two instruments A8
compares do not resolve alike: Java steps at 1000 ns, Python at 232 ns, a factor of about four.
Both clear the guard by a wide margin, so neither can manufacture or hide a cliff -- but the
asymmetry is real, it is in the direction that would make the Java client look *coarser*, and it
is stated here so that a Python-versus-Java difference is never read as a client difference
without it being ruled out first.

## Where the 25 microsecond bar comes from

Metrology's rule of ten: an instrument should divide the tolerance being judged into about ten
parts, and below four to one it is not a measurement of that tolerance at all.

The tolerance is not the cliff's width. It is the narrowest quantity the plan pre-registers a
bound on: P2d asks whether the fitted start stays within a quarter of a millisecond, and P3a
whether the halfway point's whole interval lies inside 0.25 ms either way. Ten parts of 250
microseconds is 25, so the bar is 25 microseconds -- not the 100 this first held, which was ten
parts of the 1 ms cliff and only 2.5 parts of the bound that actually decides P2d and P3a.

    against a 0.25 ms bound     ratio     verdict
    Windows, either runtime     1:4       refused outright
    the old 100 us bar          2.5:1     under the four-to-one floor
    the 25 us bar               10:1      the rule of ten
    Linux JVM, 1000 ns          25:1      passes
    Linux Python, 232 ns       108:1      passes

So the client measures its own clock before every run and refuses to start where it steps coarser
than 25 microseconds, naming the figure. The measurement is printed on the CONFIG line and belongs
in the run's record. This is the defect the tools audit found in others; it is cheaper to be
stopped by it than to publish it.

## The consumer, and the thread that fetches

*Words in this part.* **Fetch**: the consumer's request to the broker for the next messages.
**Poll**: the call the program makes to get messages from the client. **Thread**: one line of
work inside a program, which the operating system schedules on its own. **Offset**: a message's
number in its partition, given by the broker.

`LawConsumer` identifies each message as the broker does, by the partition and offset the client
hands back with it (`ConsumerRecord.partition()` and `offset()`), and writes both in
`consumer_events.csv`. The payload's `run_id` only decides whether a message is this run's, and
its `event_id` is only copied into its column. It ends, as `scripts/kafka_consumer.py` does, with
`OK java consumer: wrote N rows -> PATH` for each of its two files.

It uses the classic group protocol, set by name (`group.protocol=classic`), which is
kafka-clients 3.9.0's default and the only one kafka-python speaks. Under it the consumer has no
network thread of its own (kafka-clients 3.9.0, `ClassicKafkaConsumer`):

- the thread that calls `poll()` builds each fetch and sends it, and sends the next one just
  before `poll()` hands back the records it has (`poll` and `pollForFetches`);
- the broker never holds more than one fetch from it (`AbstractFetch.prepareFetchRequests` skips
  a broker with a fetch outstanding), so a message that arrives after that fetch was answered,
  while the program works on the last batch, waits at the broker for the next `poll()`;
- the heartbeat thread (`kafka-coordinator-heartbeat-thread | <group>`) polls the same network
  client between heartbeats and may read an answer off the socket, but it builds no fetch.

kafka-clients 3.9.0 has a network thread of its own only under the newer protocol
(`group.protocol=consumer`, its `consumer_background_thread`), which this harness does not use.

So the poll thread is the thread whose scheduling decides when fetches leave. The consumer names
it `law-poll`, and HotSpot passes the name to the kernel, so it is in
`/proc/<pid>/task/<tid>/comm` too. With `--threads-out PATH`, once the group has assigned the
partitions, it writes every thread of the process, one row each:

    tid           the kernel's id for the thread, which chrt -f -p 80 <tid> takes
    name          the kernel's name for it, at most 15 bytes
    role          poll+fetch for the poll thread, which finds its own id in /proc/thread-self
    runtime_name  the JVM's name for it, matched by those 15 bytes where no other thread shares them

The file is the same in `scripts/kafka_consumer_confluent.py` and `harness/go`, and it is written
beside the path and then moved onto it, so a reader never sees half a list.

## Building and checking

`build.sh` fetches two jars from Maven Central and refuses to build if either has changed under
us, because which build of Kafka's client ran is part of what A8 reports:

    org.apache.kafka:kafka-clients  3.9.0
    org.slf4j:slf4j-api             1.7.36

Their SHA-256 fingerprints are in `DEPENDENCIES`, which holds checksum lines and nothing else so
that `sha256sum -c` reads it without complaint. The jars themselves are not committed.

    bash build.sh

or, by hand:

    javac -d out -cp "lib/kafka-clients.jar:lib/slf4j-api.jar" src/*.java
    java -cp out LawSelfTest

The self test needs no broker. It checks the clock reads wall time with a shared epoch, that the
guard fires exactly when the clock is too coarse, that a message survives a round trip including
a quote and a backslash in an identifier, and that the plan is read, filtered and ordered as the
Python client reads, filters and orders it.
