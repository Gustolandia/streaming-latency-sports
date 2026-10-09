"""Our own Pulsar client: the reference pulsar-perf's figures are read against (freeze 30, D33-6).

pulsar-perf produces from one process and consumes in another, through one broker, and its
consumer times the interval from the producer's publish stamp to its own clock. T2 takes its
offsets from a reference's median trip and predicts from its trips, so pulsar-perf needs one, and
the study's own program speaks Kafka and Redis only. This is that reference, arranged like the
NATS and MQTT ones: a producer and a consumer on one topic of its own, each message timed on the
monotonic clock from being handed to the producer to being read back, paced at the rate the tool
runs at, one message in flight at a time.

Pulsar's protocol is binary and framed in protobuf, so unlike the other two this one speaks
through the project's own client library, pinned by `tools.sh install`. The producer sends
without batching and without waiting for its acknowledgement, so what is timed is the message's
trip and not the producer's wait to hear that the broker has it.
"""
import argparse
import json
import statistics
import sys
import time


def _library(url):
    """The Pulsar client library and a client of it, imported here and nowhere else: the pair
    has it installed, and nothing else in this repository needs it."""
    import pulsar
    return pulsar, pulsar.Client(url)


def _ignore(*_):
    """send_async's callback. The acknowledgement is not what is timed."""


def trips(url, rate=50.0, seconds=130.0, warmup_s=30.0, size=512, clock=time.perf_counter_ns,
          sleep=time.sleep, library=_library, stamp=time.time_ns):
    """Paced sends read back by the consumer, as (trips in ms, sent, lost)."""
    pulsar, client = library(url)
    topic = "persistent://public/default/sbl-reference-%d" % stamp()
    consumer = client.subscribe(topic, "sbl-reference",
                                initial_position=pulsar.InitialPosition.Latest)
    producer = client.create_producer(topic, batching_enabled=False)
    #: The exception the library raises when a receive times out, asked for rather than assumed.
    timeout = getattr(pulsar, "Timeout", TimeoutError)
    start, period_ns, n = clock(), int(1e9 / rate), 0
    found, lost = [], 0
    while True:
        #: The schedule decides when to stop, as in the NATS reference.
        due = start + n * period_ns
        if due - start >= seconds * 1e9:
            break
        now = clock()
        if due > now:
            sleep((due - now) / 1e9)
        body = (b"%d " % n).ljust(size, b"x")
        began = clock()
        producer.send_async(body, _ignore)
        #: Read until this message comes back, so one that arrives late is passed over rather
        #: than read as the next one's. The library's own timeout is a loss like any other.
        back = b""
        try:
            while back.split(b" ", 1)[0] != b"%d" % n:
                message = consumer.receive(timeout_millis=5000)
                consumer.acknowledge(message)
                back = message.data()
        except (OSError, timeout):
            back = b""
        ended = clock()
        if not back:
            lost += 1
        elif began - start >= warmup_s * 1e9:
            found.append((ended - began) / 1e6)
        n += 1
    producer.close()
    consumer.close()
    client.close()
    return found, n, lost


def main(argv=None, out=None, clock=time.perf_counter_ns, sleep=time.sleep, library=_library,
         stamp=time.time_ns):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Our own Pulsar client, as the reference for T1 and T2")
    ap.add_argument("--url", required=True)
    ap.add_argument("--rate", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=130.0)
    ap.add_argument("--warmup-s", type=float, default=30.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    found, sent, lost = trips(args.url, args.rate, args.seconds, args.warmup_s, clock=clock,
                              sleep=sleep, library=library, stamp=stamp)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"client": "pulsar_reference.py", "trips_ms": found, "sent": sent,
                   "lost": lost, "target": args.url}, fh)
    if not found:
        print("no trip was timed: %d sent, %d lost" % (sent, lost), file=out)
        return 1
    print("%d trips timed of %d sent, %d lost; median %.3f ms"
          % (len(found), sent, lost, statistics.median(found)), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
