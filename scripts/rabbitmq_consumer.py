#!/usr/bin/env python3
"""
rabbitmq_consumer.py -- the run's messages taken from its RabbitMQ queue as RabbitMQ pushes them,
each acknowledged by hand once it is handled, into the two files scripts/redis_consumer.py writes.

RabbitMQ pushes a consumer its queue's messages and holds back any beyond its prefetch count
(basic.qos) still unacknowledged, a count of 0 holding back none, and applies the count to each
consumer on its own (rabbitmq.com/docs/consumer-prefetch, rabbitmq.com/docs/confirms). So at
--prefetch 1 a message leaves the broker only once the consumer's acknowledgment of the one before
has reached it, and the consumer's own time from reading a message to acknowledging it lies on the
next message's path, as a pull consumer's turnaround lies on its next request's. At --prefetch 1000
a credit is always waiting: the broker sends each message as it arrives, and a message waits instead
in the consumer's own socket and in pika until the consumer's thread reads it.

Each message is acknowledged once it is handled -- stamped, its payload read, its two rows written
-- alone (--ack-each, the default), or every --ack-batch messages with multiple set, which
acknowledges every delivery up to the tag given. A batch larger than the prefetch count would never
fill: the broker sends no more until some are acknowledged. The thread's scheduler counters are
sampled just before each acknowledgment is sent (--schedstat): the request that frees the next
message.

Every --probe-ms the consumer also asks the broker, on its own connection, for an answer that waits
for no message: a passive queue.declare of its queue, on a second channel that consumes nothing,
answered by queue.declare-ok. An acknowledgment has no reply, so at --prefetch 1000 nothing else on
the connection makes a round trip: the probes' least round trip is the connection's floor for the
crossings estimate, and their largest the run's check that every one-way delay stayed under 10 ms.
A probe holds no credit and acknowledges nothing, and the consuming channel never waits for it:
pika keeps each channel's synchronous requests to itself, and RabbitMQ runs each channel in a
process of its own. scripts/amqp_frames.py pairs each probe with its reply (probes).

consumer.csv and consumer_events.csv carry the Redis consumer's columns, the queue's name under
`stream`, and in place of `redis_id` RabbitMQ's own fields: the delivery tag, and in the event log
the message-id property, read from the message's properties. The payload is read for the run filter
and the event_id column alone. pika's blocking adapter does all its work on the calling thread, so
the thread that stamps a message is the one that acknowledges it and whose counters are sampled.

What both RabbitMQ clients share is here: the queue's declaration, the poller pika is given, the
broker's address, and the check that the socket timestamps see pika's connection.
"""
import argparse
import csv
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import law_clock
import thread_record
import so_timestamps
import client_quiet

DEFAULT_URI = "amqp://guest:guest@localhost:5672"

#: 23 Oct 2026: durable and classic, and deleted after ten minutes unused. RabbitMQ lists transient
#: non-exclusive queues among its deprecated features (transient_nonexcl_queues) and advises a
#: durable queue, with a queue TTL to clear those left behind (rabbitmq.com/release-information/
#: deprecated-features-list). The messages go transient and well under the 4,096-byte embedding
#: threshold, which the classic-queue page (rabbitmq.com/docs/classic-queues) lists among the cases
#: it keeps off the disk. Both clients declare the queue with these arguments; RabbitMQ refuses a
#: declaration that differs from the one standing.
QUEUE_ARGUMENTS = {"x-queue-type": "classic", "x-expires": 600000}

#: 23 Oct 2026: pika's select() poller, not its default epoll. In WSL's Ubuntu 22.04 with Python
#: 3.10.12, the drivers' release, epoll.poll(300 us) returned a median 789 us late (99th percentile
#: 895 us), CPython rounding epoll's timeout up to the millisecond, against 90 us for select.select
#: and 86 us for time.sleep, the Redis producer's pacing. And with SO_TIMESTAMPING on, a transmit
#: stamp waiting on the socket's error queue showed to epoll as EPOLLERR alone, which pika 1.3.2
#: hands to a writer callback and never to its reader (adapters/utils/selector_ioloop_adapter.py),
#: so a consumer waiting for its next delivery would spin until it came; select showed the socket
#: readable, so pika reads it and the socket timestamps drain the queue.
POLLER = "select"


def now_ns():
    """Wall-clock epoch nanoseconds, time.time_ns, as the other clients stamp: one epoch with the
    producer's process, so that a difference of the two is a latency."""
    return time.time_ns()


def queue_name(run_id):
    """The run's own queue, unless the run names one."""
    return "sb-events-%s" % run_id


def broker_port(uri):
    """The broker's port in an AMQP URI, or the protocol's own."""
    parts = urlsplit(uri)
    return parts.port or (5671 if parts.scheme == "amqps" else 5672)


def broker_address(uri):
    """host:port, without the credentials the URI carries, for the logs."""
    return "%s:%d" % (urlsplit(uri).hostname, broker_port(uri))


def load_pika():
    """pika, imported only when a client runs, so the tests need nothing installed: the driver has
    it, pinned by cloud/azure/tools.sh install."""
    import pika
    return pika


def use_select(pika):
    """Give pika the select() poller, before any connection makes its loop; returns its name."""
    pika.adapters.select_connection.SELECT_TYPE = POLLER
    return POLLER


def declare(channel, queue, **callback):
    """The queue, declared as both clients declare it; the asynchronous channel takes a
    callback."""
    return channel.queue_declare(queue=queue, durable=True, arguments=dict(QUEUE_ARGUMENTS),
                                 **callback)


def check_shim(so, port, who):
    """How many of the client's connections to the broker the socket timestamps took, or None
    when the run did not ask for them. They replace socket.socket before the client connects, and
    pika 1.3.2 makes its socket through socket.socket at connect time and reads and writes it with
    recv() and send() (adapters/utils/connection_workflow.py, AMQPConnector.start, and
    io_services_utils.py); a connection they never saw would leave the run with no kernel
    timestamps, so it stops here."""
    if so is None:
        return None
    if not so.counts["connections"] + so.counts["refused"]:
        raise SystemExit("%s: the socket timestamps saw no connection to port %d, so pika made "
                         "its socket where they cannot reach it" % (who, port))
    return so.counts["connections"]


class Receiver(object):
    """What the consumer does with each message pika hands it: stamp it, read its run and event
    from the payload, write its two rows, and acknowledge it, alone or in batches."""

    def __init__(self, run_id, queue, out, events, files, batch, multiple, quiet, record):
        self.run_id, self.queue = run_id, queue
        self.out, self.events, self.files = out, events, files
        self.batch, self.multiple = batch, multiple
        self.quiet, self.record = quiet, record
        self.seen = self.rows = self.pending = 0
        self.last_tag = None

    def __call__(self, channel, method, properties, body):
        t_consume_ns = now_ns()
        t_cons_recv_ns = t_consume_ns
        if self.record is not None:
            self.record.note("stamps_receive")
        self.seen += 1
        tag = method.delivery_tag
        msg = json.loads(body)
        if msg.get("run_id") != self.run_id:
            # 23 Oct 2026: another run's message is acknowledged at once and alone: at --prefetch 1
            # one left unacknowledged would hold back every message after it.
            self.acknowledge(channel, tag, False)
            return
        t_output_ns = now_ns()
        self.out.writerow({
            "run_id": self.run_id,
            "backend": "rabbitmq",
            "stream": self.queue,
            "event_id": msg.get("event_id"),
            "match_id": msg.get("match_id"),
            "t_sim_seconds": msg.get("t_sim_seconds"),
            "t_cons_recv_ns": t_cons_recv_ns,
            "t_output_ns": t_output_ns,
            "delivery_tag": tag,
        })
        self.events.writerow({
            "run_id": self.run_id,
            "backend": "rabbitmq",
            "stream": self.queue,
            "message_id": properties.message_id,
            "delivery_tag": tag,
            "t_consume_ns": t_consume_ns,
            "event_id": msg.get("event_id"),
            "match_id": msg.get("match_id"),
            "t_sim_seconds": msg.get("t_sim_seconds"),
            "t_emit_offset_s": msg.get("t_emit_offset_s"),
            "t_emit_planned_ns": msg.get("t_emit_planned_ns"),
            "s3_uid": msg.get("s3_uid"),
            "s3_rev": msg.get("s3_rev"),
            "s3_is_correction": msg.get("s3_is_correction"),
        })
        self.rows += 1
        if self.rows % 2000 == 0:
            for fh in self.files:
                fh.flush()
        self.pending += 1
        self.last_tag = tag
        if self.pending >= self.batch:
            self.flush(channel)

    def acknowledge(self, channel, tag, multiple):
        """The thread's counters, then the acknowledgment, which pika sends before it returns."""
        client_quiet.sample(self.quiet)
        channel.basic_ack(delivery_tag=tag, multiple=multiple)

    def flush(self, channel):
        """Acknowledge every message handled and not yet acknowledged."""
        if self.pending:
            self.acknowledge(channel, self.last_tag, self.multiple)
            self.pending = 0


class Prober(object):
    """Every `interval` seconds, a request the broker answers without waiting for a message, on the
    consumer's own connection: a passive queue.declare of the queue on a channel of its own,
    answered by queue.declare-ok. While one is unanswered the next is not sent, but counted.

    23 Oct 2026: pika 1.3.2's blocking channel sends a synchronous method and then drives the loop
    until the reply comes (BlockingChannel.queue_declare), and a delivery that came meanwhile would
    wait for the consumer with it. So the probe goes out on the asynchronous channel under the
    blocking one (BlockingChannel._impl), which hands it to the connection and returns, and is
    timed by a timer of the loop under the connection (BlockingConnection._impl.ioloop), of the
    producer's own kind: the probe is written, and its reply read, in whichever turn of that loop
    the consumer's thread is making, waiting for a message or sending an acknowledgment, and no
    other thread touches the connection. Neither the timer nor the reply ends the wait of
    process_data_events, as a timer of the blocking connection's own (call_later) would: the loop
    in main() would then acknowledge a batch's remainder at the next probe rather than after an
    empty wait.

    23 Oct 2026: a passive declaration of the run's own queue is refused nowhere the consumer is
    let in, the queue being the one it declared and consumes from. RabbitMQ 4.3.7, the testbed's,
    answers it once the queue's own process has counted the messages and consumers its reply
    carries (rabbit_channel.erl, maybe_stat; rabbit_classic_queue:stat, a gen_server2 call), so
    each probe takes one turn of the process that sends the consumer its messages, and its reply
    waits while that process is busy: the least round trip holds that turn, and the largest the
    longest a probe waited for one. channel.flow with active set, which 4.3.7 answers from the
    channel alone, would be lighter, but RabbitMQ supports channel.flow only in part
    (rabbitmq.com/docs/specification), and the part it does not, active unset, closes the whole
    connection (NOT_IMPLEMENTED), where a declaration refused closes the probe's channel alone
    (NOT_FOUND)."""

    def __init__(self, connection, channel, queue, interval):
        self.loop = connection._impl.ioloop
        self.channel = channel._impl
        self.number = channel.channel_number
        self.queue, self.interval = queue, interval
        self.sent = self.answered = self.skipped = 0
        self.waiting = False
        self.timer = None

    def start(self):
        """The first probe, `interval` from now."""
        self.timer = self.loop.call_later(self.interval, self.due)

    def due(self):
        """The loop's timer: the next probe, unless the last is unanswered, and the timer set again;
        nothing more once the broker has closed the probe's channel."""
        if not self.channel.is_open:
            self.timer = None
            return
        self.timer = self.loop.call_later(self.interval, self.due)
        if self.waiting:
            self.skipped += 1
            return
        self.waiting = True
        self.sent += 1
        self.channel.queue_declare(queue=self.queue, passive=True, callback=self.answer)

    def answer(self, _frame):
        """queue.declare-ok, read in a turn of the loop."""
        self.waiting = False
        self.answered += 1

    def stop(self):
        """No probe after this one. One unanswered is answered before its channel closes: pika sends
        a channel's close only once its last synchronous request is answered (Channel._rpc)."""
        if self.timer is not None:
            self.loop.remove_timeout(self.timer)
            self.timer = None


def main(argv=None, pika=None, clock=time.monotonic):
    ap = argparse.ArgumentParser(
        description="The run's messages from its RabbitMQ queue, each acknowledged by hand")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--uri", default=DEFAULT_URI, help="amqp://user:password@host:port[/vhost]")
    ap.add_argument("--queue", default=None, help="the run's own queue; sb-events-<run id> unless "
                                                  "named")
    ap.add_argument("--idle-seconds", type=int, default=15)
    ap.add_argument("--prefetch", type=int, default=1,
                    help="basic.qos prefetch count: the unacknowledged messages RabbitMQ may push "
                         "this consumer; 0 is no limit")
    ack = ap.add_mutually_exclusive_group()
    ack.add_argument("--ack-each", action="store_true",
                     help="acknowledge each message once it is handled (the default)")
    ack.add_argument("--ack-batch", type=int, default=None,
                     help="acknowledge every N messages handled at once, with multiple set")
    ap.add_argument("--block-ms", type=int, default=1000,
                    help="the longest wait for a message before the idle check")
    ap.add_argument("--probe-ms", type=int, default=100,
                    help="every N ms, a passive queue.declare of the queue on a second channel: a "
                         "round trip the broker answers without a message; 0 sends none")
    ap.add_argument("--thread-record", action="store_true",
                    help="write which thread stamped the arrivals, and both clocks, beside the CSV")
    so_timestamps.add_arguments(ap)
    client_quiet.add_arguments(ap)
    args = ap.parse_args(argv)
    batch = 1 if args.ack_batch is None else args.ack_batch
    multiple = args.ack_batch is not None
    if args.prefetch < 0:
        ap.error("--prefetch is a count of messages, 0 for no limit, not %d" % args.prefetch)
    if batch < 1:
        ap.error("--ack-batch is at least 1, not %d" % batch)
    if args.prefetch and batch > args.prefetch:
        ap.error("--ack-batch %d is more than the %d unacknowledged messages --prefetch lets the "
                 "broker send, so a batch would never fill" % (batch, args.prefetch))
    if args.probe_ms < 0:
        ap.error("--probe-ms is the time between probes in ms, 0 for none, not %d" % args.probe_ms)
    record = thread_record.ThreadRecord() if args.thread_record else None
    port = broker_port(args.uri)
    so = so_timestamps.start(args, port)
    queue = args.queue or queue_name(args.run_id)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    events_path = out_path.with_name(out_path.stem + "_events.csv")
    resolution = law_clock.demand_usable_resolution("the RabbitMQ consumer")

    pika = pika or load_pika()
    poller = use_select(pika)
    connection = pika.BlockingConnection(pika.URLParameters(args.uri))
    channel = connection.channel()
    declare(channel, queue)
    channel.basic_qos(prefetch_count=args.prefetch, global_qos=False)
    sockets = check_shim(so, port, "the RabbitMQ consumer")
    prober = None if not args.probe_ms else Prober(
        connection, connection.channel(), queue, args.probe_ms / 1000.0)
    print("CONFIG effective prefetch=%d ack_batch=%d ack_multiple=%s probe_ms=%d probe_channel=%s "
          "poller=%s queue=%s broker=%s so_connections=%s client=python clock_resolution_ns=%d"
          % (args.prefetch, batch, multiple, args.probe_ms,
             None if prober is None else prober.number, poller, queue, broker_address(args.uri),
             sockets, resolution), flush=True)
    # 23 Oct 2026: as in the other clients since freeze 43, whose pilot found the clients' pauses
    # to be CPython's full collections, the collector goes off where the run asks once the client
    # is connected and before any message is taken, from the thread that acknowledges them.
    quiet = client_quiet.start(args)

    with out_path.open("w", newline="", encoding="utf-8") as f_out, events_path.open(
            "w", newline="", encoding="utf-8") as f_events:
        out = csv.DictWriter(f_out, fieldnames=[
            "run_id", "backend", "stream", "event_id", "match_id", "t_sim_seconds",
            "t_cons_recv_ns", "t_output_ns", "delivery_tag"])
        out.writeheader()
        events = csv.DictWriter(f_events, fieldnames=[
            "run_id", "backend", "stream", "message_id", "delivery_tag", "t_consume_ns",
            "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s", "t_emit_planned_ns",
            "s3_uid", "s3_rev", "s3_is_correction"])
        events.writeheader()
        receiver = Receiver(args.run_id, queue, out, events, (f_out, f_events), batch, multiple,
                            quiet, record)
        channel.basic_consume(queue=queue, on_message_callback=receiver, auto_ack=False)
        if prober is not None:
            prober.start()
        last = clock()
        while True:
            seen = receiver.seen
            connection.process_data_events(time_limit=args.block_ms / 1000.0)
            if receiver.seen != seen:
                last = clock()
                continue
            receiver.flush(channel)
            if clock() - last >= args.idle_seconds:
                break
    if prober is not None:
        prober.stop()
    connection.close()

    if record is not None:
        record.write(thread_record.beside(out_path))
    so_timestamps.finish(so, args)
    client_quiet.finish(quiet, args)
    print("OK rabbitmq consumer: wrote %d rows -> %s" % (receiver.rows, out_path))
    print("OK rabbitmq consumer: wrote %d rows -> %s" % (receiver.rows, events_path))
    if prober is not None:
        print("OK rabbitmq consumer: %d probes on channel %d, %d answered, %d not sent while one "
              "was unanswered" % (prober.sent, prober.number, prober.answered, prober.skipped))


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    main()
