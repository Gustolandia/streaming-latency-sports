"""Our own AMQP client: the reference rabbitmq-perftest's figures are read against.

PerfTest runs a producer and a consumer in one process, each on its own connection, and times a
message from being published to being delivered. We had no AMQP client of our own, so it had no
reference, and T2 -- which takes its offsets from the reference's median trip and predicts from
its trips -- could not be asked of it. This is that reference, arranged as PerfTest arranges
itself: two connections to one broker, a queue of our own, a publish on one and a consumer on the
other, each message timed on the monotonic clock from publish to delivery, paced at the rate
PerfTest runs at.

The client is pika, installed pinned by the tools block's install step. It is imported only when
this runs, so the tests need nothing installed.
"""
import argparse
import json
import statistics
import sys
import time

#: How long a message may take before it is counted lost. Generous: a message a broker on the
#: same subnet takes this long over is not a trip anyone is measuring.
LOST_AFTER_S = 5.0


def _pika_connect(uri):
    def connect():
        import pika  # noqa: E402 -- installed on the driver by tools.sh install, pinned
        return pika.BlockingConnection(pika.URLParameters(uri))
    return connect


def trips(uri, rate=50.0, seconds=130.0, warmup_s=30.0, size=512,
          clock=time.perf_counter_ns, sleep=time.sleep, connect=None):
    """Paced publishes delivered to our consumer, as (trips in ms, sent, lost)."""
    connect = connect or _pika_connect(uri)
    producer, consumer = connect(), connect()
    out_ch, in_ch = producer.channel(), consumer.channel()
    queue = in_ch.queue_declare(queue="", exclusive=True, auto_delete=True).method.queue
    got = {}

    def delivered(_channel, _method, _properties, body):
        got.setdefault(body.split(b" ", 1)[0], clock())

    def too_late():
        got["late"] = True

    in_ch.basic_consume(queue=queue, on_message_callback=delivered, auto_ack=True)
    start, period_ns, n = clock(), int(1e9 / rate), 0
    found, lost = [], 0
    while True:
        #: The schedule decides when to stop, not the clock after the last answer: a message due
        #: at the end of the run is one past it, and the rate asked for is what is sent.
        due = start + n * period_ns
        if due - start >= seconds * 1e9:
            break
        now = clock()
        if due > now:
            sleep((due - now) / 1e9)
        key = b"%d" % n
        got.pop("late", None)
        began = clock()
        out_ch.basic_publish(exchange="", routing_key=queue, body=(key + b" ").ljust(size, b"x"))
        timer = consumer.call_later(LOST_AFTER_S, too_late)
        while key not in got and "late" not in got:
            consumer.process_data_events(time_limit=None)
        consumer.remove_timeout(timer)
        arrived = got.pop(key, None)
        n += 1
        if arrived is None:
            lost += 1
        elif began - start >= warmup_s * 1e9:
            found.append((arrived - began) / 1e6)
    producer.close()
    consumer.close()
    return found, n, lost


def main(argv=None, out=None, connect=None, clock=time.perf_counter_ns, sleep=time.sleep):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Our own AMQP client, as the reference for T1 and T2")
    ap.add_argument("--uri", required=True)
    ap.add_argument("--rate", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=130.0)
    ap.add_argument("--warmup-s", type=float, default=30.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    found, sent, lost = trips(args.uri, args.rate, args.seconds, args.warmup_s, clock=clock,
                              sleep=sleep, connect=connect)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"client": "amqp_reference.py", "trips_ms": found, "sent": sent, "lost": lost,
                   "target": args.uri.split("@")[-1]}, fh)
    if not found:
        print("no trip was timed: %d sent, %d lost" % (sent, lost), file=out)
        return 1
    print("%d trips timed of %d sent, %d lost; median %.3f ms"
          % (len(found), sent, lost, statistics.median(found)), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
