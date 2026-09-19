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
and do not always get an answer of the same fineness. Measured here on Windows, the JVM's clock
steps in about a millisecond; on Linux the same call steps far finer. Our trips run from under a
millisecond to about fourteen, and the cliff the law predicts is one millisecond wide, so a
millisecond-stepping clock would report tidy whole numbers and see none of the structure --
and A8 would be comparing two clocks rather than two clients.

So the client measures its own clock before every run and refuses to start where it steps coarser
than 100 microseconds, naming the figure. The measurement is printed on the CONFIG line and
belongs in the run's record. This is the defect the tools audit found in others; it is cheaper to
be stopped by it than to publish it.

## Building and checking

    javac -d out -cp "lib/kafka-clients.jar:lib/slf4j-api.jar" src/*.java
    java -cp out LawSelfTest

The self test needs no broker. It checks the clock reads wall time with a shared epoch, that the
guard fires exactly when the clock is too coarse, that a message survives a round trip including
a quote and a backslash in an identifier, and that the plan is read, filtered and ordered as the
Python client reads, filters and orders it.
